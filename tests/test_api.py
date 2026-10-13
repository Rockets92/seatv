import asyncio

import pytest

from conftest import NOW, sky_handler

from seatv.ingest import run_ingest
from seatv.sources.sky import SkySource
from seatv.sources.tivu import TivuSource


@pytest.fixture
def loaded(api, settings, tivu_client):
    asyncio.run(run_ingest(settings, api.app.state.db, client=tivu_client, sources=[TivuSource()], now=NOW))
    return api


def test_channels(loaded):
    response = loaded.get("/channels", params={"platform": "dtt"})
    assert response.status_code == 200
    assert [(c["id"], c["numbers"]["dtt"]) for c in response.json()] == [("rai1", 1), ("canale5", 5), ("la7", 7)]
    assert len(loaded.get("/channels").json()) == 4


def test_channel_unknown(loaded):
    assert loaded.get("/channels/nope").status_code == 404
    assert loaded.get("/channels/nope/schedule").status_code == 404


def test_bad_platform(loaded):
    assert loaded.get("/channels", params={"platform": "cable"}).status_code == 422


def test_schedule(loaded):
    response = loaded.get("/channels/rai1/schedule", params={"date": "2026-10-12"})
    assert response.status_code == 200
    body = response.json()
    assert body["channel"]["name"] == "Rai 1"
    # Lo "Speciale notte" iniziato l'11 non appartiene al 12.
    assert [p["title"] for p in body["programmes"]] == ["Tg1", "Unomattina", "Tg1", "Film della sera"]
    assert body["programmes"][0]["start"] == "2026-10-12T06:00:00+02:00"
    assert loaded.get("/channels/rai1/schedule", params={"date": "2026-10-20"}).json()["programmes"] == []


def test_now(loaded):
    response = loaded.get("/now", params={"platform": "dtt", "at": "2026-10-12T07:00:00+02:00"})
    assert response.status_code == 200
    entries = {e["channel"]["id"]: e for e in response.json()}
    assert entries["rai1"]["now"]["title"] == "Unomattina"
    assert entries["rai1"]["next"]["start"] == "2026-10-12T20:00:00+02:00"
    assert entries["la7"]["now"] is None


def test_channel_now_naive_time_is_rome(loaded):
    body = loaded.get("/channels/rai1/now", params={"at": "2026-10-12T21:00:00"}).json()
    assert body["now"] is None
    assert body["next"]["title"] == "Film della sera"


def test_health(loaded):
    body = loaded.get("/health").json()
    assert body["status"] == "ok"
    assert body["sources"][0]["source"] == "tivu"
    assert body["sources"][0]["programmes"] == 5


def test_health_degraded_before_first_ingest(api):
    assert api.get("/health").json() == {"status": "degraded", "sources": []}


def test_guide(loaded):
    body = loaded.get("/guide", params={"date": "2026-10-12", "platform": "dtt"}).json()
    assert body["date"] == "2026-10-12"
    rows = {r["channel"]["id"]: r for r in body["channels"]}
    assert list(rows) == ["rai1", "canale5", "la7"]
    assert rows["rai1"]["channel"]["sources"] == ["tivu"]
    titles = [p["title"] for p in rows["rai1"]["programmes"]]
    # A differenza di /schedule, la griglia include anche il programma iniziato
    # il giorno prima e ancora in onda dopo mezzanotte.
    assert titles == ["Speciale notte", "Tg1", "Unomattina", "Tg1", "Film della sera"]
    assert rows["rai1"]["programmes"][1]["source"] == "tivu"
    assert rows["la7"]["programmes"] == []


def test_web_page(api):
    page = api.get("/")
    assert page.status_code == 200
    assert "SEA-TV" in page.text
    assert api.get("/static/guide.js").status_code == 200
    assert api.get("/static/guide.css").status_code == 200
    assert api.get("/static/logo.png").headers["content-type"] == "image/png"
    assert api.get("/favicon.ico").status_code == 200


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_channel_logo_is_cached(settings, tivu_client):
    import httpx
    from fastapi.testclient import TestClient

    from seatv.main import create_app

    calls: list[str] = []

    def logos(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("rai1hd.png"):
            return httpx.Response(200, content=PNG)
        return httpx.Response(200, content=b"<svg onload=alert(1)></svg>")

    app = create_app(settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(logos)))
    with TestClient(app) as client:
        asyncio.run(run_ingest(settings, app.state.db, client=tivu_client, sources=[TivuSource()], now=NOW))
        first = client.get("/channels/rai1/logo")
        assert first.status_code == 200
        assert first.headers["content-type"] == "image/png"
        assert first.content == PNG
        assert client.get("/channels/rai1/logo").content == PNG
        assert calls == ["https://services.tivulaguida.it/uploads/channel/rai1hd.png"]
        # Ciò che non è un'immagine raster (qui un SVG) non viene servito da noi:
        # il browser viene rimandato alla fonte.
        svg = client.get("/channels/canale5/logo", follow_redirects=False)
        assert svg.status_code == 307
        assert svg.headers["location"].startswith("https://services.tivulaguida.it/")
        assert client.get("/channels/nope/logo").status_code == 404


def test_channel_logo_falls_back_to_other_versions(settings):
    import httpx
    from fastapi.testclient import TestClient

    from seatv.main import create_app

    calls: list[str] = []

    def logos(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers["user-agent"].startswith("Mozilla/")
        if request.url.path.endswith("_Light_Padding.png"):
            return httpx.Response(200, content=PNG)
        return httpx.Response(404)

    app = create_app(settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(logos)))
    with TestClient(app) as client:
        sky_client = httpx.AsyncClient(transport=httpx.MockTransport(sky_handler([])))
        asyncio.run(run_ingest(settings, app.state.db, client=sky_client, sources=[SkySource()], now=NOW))
        response = client.get("/channels/skyuno/logo")
        assert response.status_code == 200
        assert response.content == PNG
        assert calls == ["/logo/skyuno_Light_Fit.png", "/logo/skyuno_Light_Padding.png"]


def test_docs_page_is_branded(api):
    page = api.get("/docs")
    assert page.status_code == 200
    assert "/static/docs.css" in page.text
    assert "/static/logo.png" in page.text
    assert api.get("/static/docs.css").status_code == 200
