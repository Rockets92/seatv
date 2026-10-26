import dataclasses
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from conftest import FIXTURES, NOW, combined_handler, sky_handler

from seatv.collect import collect
from seatv.model import Guide
from seatv.sources.sky import SkySource
from seatv.sources.tivu import TivuSource
from seatv.sources.xmltv import XmltvSource


def ids(channels):
    return [c.id for c in channels]


@pytest.mark.anyio
async def test_tivu(settings, tivu_client):
    guide = await collect(settings, client=tivu_client, sources=[TivuSource()], now=NOW)
    [run] = guide.runs
    assert run.error is None
    # "Rai 1" e "Rai 1 HD" diventano un solo canale.
    assert run.channels == 4
    assert run.programmes == 5

    rai1 = guide.channels["rai1"]
    assert rai1.name == "Rai 1"
    assert rai1.aliases == ["Rai 1 HD"]
    # Su Tivùsat vince il numero più basso (1 per la versione HD, non 101).
    assert rai1.numbers == {"dtt": 1, "tivusat": 1}
    assert ids(guide.sorted_channels("dtt")) == ["rai1", "canale5", "la7"]
    assert ids(guide.sorted_channels("tivusat")) == ["rai1", "canale5", "mezzo"]
    # Lo "Speciale notte" iniziato l'11 finisce dopo mezzanotte: resta nella guida.
    assert [p.title for p in guide.programmes["rai1"]] == ["Speciale notte", "Tg1", "Unomattina", "Tg1", "Film della sera"]


@pytest.mark.anyio
async def test_prune_drops_finished_programmes(settings, tivu_client):
    guide = await collect(settings, client=tivu_client, sources=[TivuSource()], now=NOW)
    # Dalla mezzanotte del 13 resta solo il film finito alle 00:10.
    guide.prune(datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc))
    assert [p.title for p in guide.programmes["rai1"]] == ["Film della sera"]


@pytest.mark.anyio
async def test_xmltv(settings):
    content = (FIXTURES / "sample.xmltv.xml").read_bytes()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content)))
    guide = await collect(settings, client=client, sources=[XmltvSource("https://example.org/guide.xml")], now=NOW)
    [run] = guide.runs
    assert run.error is None
    assert run.channels == 2
    # Il programma del 14 ottobre è fuori dai due giorni richiesti.
    assert run.programmes == 3


@pytest.mark.anyio
async def test_broken_source_is_recorded(settings):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    guide = await collect(settings, client=client, sources=[TivuSource()], now=NOW)
    assert guide.runs[0].error and "503" in guide.runs[0].error
    assert guide.programmes == {}


@pytest.mark.anyio
async def test_tivu_and_sky(settings):
    requests: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(combined_handler(requests)))
    guide = await collect(settings, client=client, sources=[TivuSource(), SkySource()], now=NOW)
    assert [r.error for r in guide.runs] == [None, None]

    # Rai 1 di Tivù e "Rai 1 HD" di Sky sono lo stesso canale, con nome e primo logo di Tivù.
    rai1 = guide.channels["rai1"]
    assert rai1.numbers == {"dtt": 1, "tivusat": 1, "sky": 101}
    assert rai1.name == "Rai 1"
    assert rai1.sources == ["sky", "tivu"]
    assert rai1.logo_urls[0].startswith("https://services.tivulaguida.it/")
    assert ids(guide.sorted_channels("sky")) == ["skytg24", "rai1", "canale5", "skyuno", "skyunoplus1"]

    # Il palinsesto di Rai 1 arriva già da Tivù: Sky serve solo a confrontare gli orari.
    sky_event_channels = {r.url.params.get("channels") for r in requests if r.url.path == "/gtv/v1/events"}
    assert guide.programmes["rai1"][0].source == "tivu"
    # Canale 5 su Tivù non ha dati (errore 500), quindi si prova con Sky.
    assert "8005" in sky_event_channels
    assert guide.runs[1].programmes == 2
    assert guide.programmes["skytg24"][0].title == "Buongiorno"
    assert guide.programmes["skytg24"][0].source == "sky"


@pytest.mark.anyio
async def test_dtt_falls_back_to_sky_when_tivu_is_down(settings, caplog):
    requests: list[httpx.Request] = []
    sky = combined_handler(requests)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "services.tivulaguida.it":
            raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)
        return sky(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    guide = await collect(settings, client=client, sources=[TivuSource(), SkySource()], now=NOW)
    tivu, sky_run = guide.runs

    assert tivu.error == "ConnectError: [Errno 11001] getaddrinfo failed"
    # Una riga di log, senza traceback.
    assert "fonte tivu fallita: [Errno 11001] getaddrinfo failed (https://services.tivulaguida.it/api/epg/channels.json)" in caplog.text
    assert "Traceback" not in caplog.text
    assert sky_run.error is None

    # Senza Tivù i canali nazionali prendono i numeri DTT di riserva...
    assert guide.channels["rai1"].numbers == {"sky": 101, "dtt": 1}
    assert ids(guide.sorted_channels("dtt")) == ["rai1", "canale5"]
    # ...e il palinsesto lo chiede Sky.
    assert "8001" in {r.url.params.get("channels") for r in requests if r.url.path == "/gtv/v1/events"}


@pytest.mark.anyio
async def test_failed_source_reuses_previous_guide(settings, tivu_client):
    previous = await collect(settings, client=tivu_client, sources=[TivuSource()], now=NOW)
    # Passa da un'istantanea su file, come tra due aggiornamenti.
    previous = Guide.from_json(previous.to_json())

    down = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    later = NOW + timedelta(hours=14)  # 21:00 del 12
    guide = await collect(settings, client=down, sources=[TivuSource()], now=later, previous=previous)

    assert guide.runs[0].error
    assert guide.runs[0].reused == 1
    assert guide.channels["rai1"].numbers == {"dtt": 1, "tivusat": 1}
    assert guide.channels["rai1"].aliases == ["Rai 1 HD"]
    # Si tengono i programmi non ancora finiti all'inizio della giornata.
    assert [p.title for p in guide.programmes["rai1"]] == ["Speciale notte", "Tg1", "Unomattina", "Tg1", "Film della sera"]


@pytest.mark.anyio
async def test_working_source_does_not_reuse_previous_guide(settings, tivu_client):
    previous = await collect(settings, client=tivu_client, sources=[TivuSource()], now=NOW)
    empty = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"channels": []} if r.url.path.endswith("channels.json") else {"events": []})
    ))
    guide = await collect(settings, client=empty, sources=[TivuSource()], now=NOW, previous=previous)
    assert guide.programmes == {}


@pytest.mark.anyio
async def test_tivu_base_url_is_configurable(settings):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(200, json={"channels": [{"id": 42, "name": "Rai 1 HD", "icon": "x.png", "is_dtt": True, "channel_dtt": 1}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    guide = await collect(settings, client=client, sources=[TivuSource(base_url="https://tivu.example.org/")], now=NOW)
    assert set(seen) == {"tivu.example.org"}
    assert guide.channels["rai1"].logo_urls == ["https://tivu.example.org/x.png"]


@pytest.mark.anyio
async def test_fallback_logos_from_iptv_org(settings):
    index = "channel,feed,in_use,tags,width,height,format,url\nSkyUno.it,,TRUE,,1,1,PNG,https://upload.wikimedia.org/skyuno.png\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "index.example.org":
            return httpx.Response(200, text=index)
        return sky_handler([])(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = dataclasses.replace(settings, logo_index_url="https://index.example.org/logos.csv")
    guide = await collect(settings, client=client, sources=[SkySource()], now=NOW)
    # Dopo i loghi di Sky, quello di iptv-org; il +1 usa quello del canale base.
    assert guide.channels["skyuno"].logo_urls[-1] == "https://upload.wikimedia.org/skyuno.png"
    assert guide.channels["skyunoplus1"].logo_urls[-1] == "https://upload.wikimedia.org/skyuno.png"


def test_snapshot_round_trip():
    guide = Guide(generated_at=datetime(2026, 10, 12, 3, 0, tzinfo=timezone.utc))
    guide.add_channel("rai1", "Rai 1", "tivu", {"dtt": 1}, ["https://example.org/rai1.png"], ["Rai 1 HD"])
    restored = Guide.from_json(guide.to_json())
    assert restored.channels == guide.channels
    assert restored.generated_at == guide.generated_at
