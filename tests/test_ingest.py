from datetime import datetime, timezone

import httpx
import pytest

from conftest import FIXTURES, NOW, combined_handler

from seatv.ingest import run_ingest
from seatv.sources.sky import SkySource
from seatv.sources.tivu import TivuSource
from seatv.sources.xmltv import XmltvSource


@pytest.mark.anyio
async def test_tivu_ingest(settings, db, tivu_client):
    [result] = await run_ingest(settings, db, client=tivu_client, sources=[TivuSource()], now=NOW)
    assert result.error is None
    # "Rai 1" e "Rai 1 HD" diventano un solo canale.
    assert result.channels == 4
    assert result.programmes == 5

    rai1 = db.get_channel("rai1")
    assert rai1["name"] == "Rai 1"
    # Su Tivùsat vince il numero più basso (1 per la versione HD, non 101).
    assert rai1["numbers"] == {"dtt": 1, "tivusat": 1}
    assert [c["id"] for c in db.list_channels("dtt")] == ["rai1", "canale5", "la7"]
    assert [c["id"] for c in db.list_channels("tivusat")] == ["rai1", "canale5", "mezzo"]
    assert db.last_runs()[0]["programmes"] == 5


@pytest.mark.anyio
async def test_reingest_replaces_moved_programmes(settings, db, tivu_client):
    await run_ingest(settings, db, client=tivu_client, sources=[TivuSource()], now=NOW)

    def moved(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/epg/channels.json":
            return httpx.Response(200, json={"channels": [
                {"id": 42, "name": "Rai 1 HD", "is_dtt": True, "channel_dtt": 1}
            ]})
        if request.url.path.endswith("/2026-10-12"):
            return httpx.Response(200, json={"events": [
                {"date_start": "12-10-2026 06:00", "date_end": "12-10-2026 06:35", "program": {"title": "Tg1"}},
                {"date_start": "12-10-2026 06:35", "date_end": "12-10-2026 09:00", "program": {"title": "Unomattina"}},
            ]})
        return httpx.Response(200, json={"events": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(moved))
    await run_ingest(settings, db, client=client, sources=[TivuSource()], now=NOW)

    day_start = datetime(2026, 10, 11, 22, 0, tzinfo=timezone.utc)
    day_end = datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc)
    titles = [(p["start"].hour, p["start"].minute, p["title"]) for p in db.programmes_between("rai1", day_start, day_end)]
    # Unomattina delle 06:30 è sparito; i programmi fuori dalla finestra nuova restano.
    assert titles == [(4, 0, "Tg1"), (4, 35, "Unomattina"), (18, 0, "Tg1"), (19, 30, "Film della sera")]


@pytest.mark.anyio
async def test_xmltv_ingest(settings, db):
    content = (FIXTURES / "sample.xmltv.xml").read_bytes()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content)))
    [result] = await run_ingest(settings, db, client=client, sources=[XmltvSource("https://example.org/guide.xml")], now=NOW)
    assert result.error is None
    assert result.channels == 2
    # Il programma del 14 ottobre è fuori dai due giorni richiesti.
    assert result.programmes == 3


@pytest.mark.anyio
async def test_broken_source_is_recorded(settings, db):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    [result] = await run_ingest(settings, db, client=client, sources=[TivuSource()], now=NOW)
    assert result.error and "503" in result.error
    assert db.last_runs()[0]["error"] == result.error


@pytest.mark.anyio
async def test_tivu_and_sky_ingest(settings, db):
    requests: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(combined_handler(requests)))
    results = await run_ingest(settings, db, client=client, sources=[TivuSource(), SkySource()], now=NOW)
    assert [r.error for r in results] == [None, None]

    # Rai 1 di Tivù e "Rai 1 HD" di Sky sono lo stesso canale, con nome e logo di Tivù.
    rai1 = db.get_channel("rai1")
    assert rai1["numbers"] == {"dtt": 1, "tivusat": 1, "sky": 101}
    assert rai1["name"] == "Rai 1"
    assert rai1["logo"].startswith("https://services.tivulaguida.it/")
    assert [c["id"] for c in db.list_channels("sky")] == ["skytg24", "rai1", "canale5", "skyuno", "skyunoplus1"]

    # Il palinsesto di Rai 1 arriva già da Tivù: a Sky non viene richiesto.
    sky_event_channels = {r.url.params.get("channels") for r in requests if r.url.path == "/gtv/v1/events"}
    assert "8001" not in sky_event_channels
    # Canale 5 su Tivù non ha dati (errore 500), quindi si prova con Sky.
    assert "8005" in sky_event_channels
    assert results[1].programmes == 2
    assert db.on_air(NOW, ["skytg24"])["skytg24"]["now"]["title"] == "Buongiorno"


@pytest.mark.anyio
async def test_dtt_falls_back_to_sky_when_tivu_is_down(settings, db, caplog):
    requests: list[httpx.Request] = []
    sky = combined_handler(requests)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "services.tivulaguida.it":
            raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)
        return sky(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tivu, sky_result = await run_ingest(settings, db, client=client, sources=[TivuSource(), SkySource()], now=NOW)

    assert tivu.error == "ConnectError: [Errno 11001] getaddrinfo failed"
    # Una riga di log, senza traceback.
    assert "ingestione tivu fallita: [Errno 11001] getaddrinfo failed (https://services.tivulaguida.it/api/epg/channels.json)" in caplog.text
    assert "Traceback" not in caplog.text
    assert sky_result.error is None

    # Senza Tivù i canali nazionali prendono i numeri DTT di riserva...
    assert db.get_channel("rai1")["numbers"] == {"sky": 101, "dtt": 1}
    assert [c["id"] for c in db.list_channels("dtt")] == ["rai1", "canale5"]
    # ...e il palinsesto lo chiede Sky.
    assert "8001" in {r.url.params.get("channels") for r in requests if r.url.path == "/gtv/v1/events"}


@pytest.mark.anyio
async def test_tivu_base_url_is_configurable(settings, db):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(200, json={"channels": [{"id": 42, "name": "Rai 1 HD", "icon": "x.png", "is_dtt": True, "channel_dtt": 1}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await run_ingest(settings, db, client=client, sources=[TivuSource(base_url="https://tivu.example.org/")], now=NOW)
    assert set(seen) == {"tivu.example.org"}
    assert db.get_channel("rai1")["logo"] == "https://tivu.example.org/x.png"
