from datetime import datetime, timezone

import httpx
import pytest

from conftest import FIXTURES, NOW

from seatv.ingest import run_ingest
from seatv.sources.tivu import TivuSource
from seatv.sources.xmltv import XmltvSource


@pytest.mark.anyio
async def test_tivu_ingest(settings, db, tivu_client):
    [result] = await run_ingest(settings, db, client=tivu_client, sources=[TivuSource()], now=NOW)
    assert result.error is None
    # "Rai 1" e "Rai 1 HD" diventano un solo canale.
    assert result.channels == 4
    assert result.programmes == 5

    rai1 = db.get_channel("rai-1")
    assert rai1["name"] == "Rai 1"
    # Sul satellite vince il numero più basso (1 per la versione HD, non 101).
    assert rai1["numbers"] == {"dtt": 1, "sat": 1}
    assert [c["id"] for c in db.list_channels("dtt")] == ["rai-1", "canale-5", "la7"]
    assert [c["id"] for c in db.list_channels("sat")] == ["rai-1", "canale-5", "mezzo"]
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
    titles = [(p["start"].hour, p["start"].minute, p["title"]) for p in db.programmes_between("rai-1", day_start, day_end)]
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
