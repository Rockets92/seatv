import dataclasses
import gzip
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest

from conftest import NOW, combined_handler

from seatv.build import build, load_snapshot
from seatv.export.xmltv import xmltv_time
from seatv.sources.sky import SkySource
from seatv.sources.tivu import TivuSource

TOKEN = "prova-token-segreto-1234"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def site_handler(logo_calls: list[str] | None = None):
    sources = combined_handler([])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith(("/uploads/", "/logo/")):
            if logo_calls is not None:
                logo_calls.append(str(request.url))
            # Solo il logo di Rai 1 è un'immagine valida.
            if request.url.path.endswith("rai1hd.png"):
                return httpx.Response(200, content=PNG)
            return httpx.Response(404)
        return sources(request)

    return handler


@pytest.fixture
def secret_settings(settings):
    return dataclasses.replace(settings, feed_token=TOKEN, public_url="https://seatv.pages.dev")


async def run_build(settings, logo_calls=None, handler=None):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler or site_handler(logo_calls)))
    return await build(settings, client=client, sources=[TivuSource(), SkySource()], now=NOW)


@pytest.mark.anyio
async def test_site_layout(secret_settings):
    health = await run_build(secret_settings)
    out = Path(secret_settings.out_dir)
    site = out / TOKEN

    # Nella radice non c'è nessun dato: solo una pagina vuota e le regole per Pages.
    root = {p.name for p in out.iterdir()}
    assert root == {"404.html", "_headers", "favicon.ico", "index.html", "robots.txt", TOKEN}
    assert "Disallow: /" in (out / "robots.txt").read_text()
    headers = (out / "_headers").read_text()
    assert "X-Robots-Tag: noindex" in headers
    assert "Referrer-Policy: no-referrer" in headers
    assert f"/{TOKEN}/epg.xml.gz\n  Content-Type: application/gzip" in headers

    for name in ["index.html", "epg.xml", "epg.xml.gz", "static/guide.js", "static/guide.css", "static/logo.png",
                 "api/health.json", "api/channels.json", "api/channels/rai1.json",
                 "api/guide/2026-10-12.json", "api/guide/2026-10-13.json", "logos/rai1.png"]:
        assert (site / name).is_file(), name
    # La pagina usa solo indirizzi relativi, così funziona sotto /<token>/.
    page = (site / "index.html").read_text()
    assert 'src="/' not in page and 'href="/' not in page

    assert health["status"] == "ok"
    assert health["days"] == ["2026-10-12", "2026-10-13"]
    assert health["feeds"] == {"xml.gz": "epg.xml.gz", "xml": "epg.xml"}
    assert json.loads((site / "api/health.json").read_text()) == health


@pytest.mark.anyio
async def test_xmltv_feed(secret_settings):
    await run_build(secret_settings)
    site = Path(secret_settings.out_dir) / TOKEN
    xml = (site / "epg.xml").read_bytes()
    assert gzip.decompress((site / "epg.xml.gz").read_bytes()) == xml

    root = ET.fromstring(xml)
    assert root.tag == "tv"
    channels = {c.get("id"): c for c in root.iter("channel")}
    assert list(channels)[:3] == ["rai1", "canale5", "la7"]
    rai1 = channels["rai1"]
    assert [d.text for d in rai1.iter("display-name")] == ["Rai 1", "Rai 1 HD"]
    # Logo scaricato e pubblicato: indirizzo assoluto sul sito.
    assert rai1.find("icon").get("src") == f"https://seatv.pages.dev/{TOKEN}/logos/rai1.png"
    # Logo non scaricabile: resta l'indirizzo originale.
    assert channels["canale5"].find("icon").get("src").startswith("https://services.tivulaguida.it/")

    programmes = [p for p in root.iter("programme") if p.get("channel") == "rai1"]
    assert [p.findtext("title") for p in programmes] == ["Speciale notte", "Tg1", "Unomattina", "Tg1", "Film della sera"]
    tg1 = programmes[1]
    assert tg1.get("start") == "20261012060000 +0200"
    assert tg1.get("stop") == "20261012063000 +0200"
    assert tg1.findtext("desc") == "Notiziario."
    assert tg1.find("icon").get("src") == "https://example.org/tg1.jpg"

    sky = [p for p in root.iter("programme") if p.get("channel") == "skytg24"]
    # "Informazione/News" di Sky diventa due categorie.
    assert [c.text for c in sky[0].iter("category")] == ["Informazione", "News"]


def test_xmltv_time_handles_dst():
    from datetime import datetime, timezone

    assert xmltv_time(datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)) == "20261025023000 +0200"
    assert xmltv_time(datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)) == "20261025023000 +0100"


@pytest.mark.anyio
async def test_guide_and_channel_json(secret_settings):
    await run_build(secret_settings)
    api = Path(secret_settings.out_dir) / TOKEN / "api"

    day = json.loads((api / "guide/2026-10-12.json").read_text())
    rows = {r["channel"]["id"]: r for r in day["channels"]}
    assert list(rows)[:3] == ["rai1", "canale5", "la7"]
    assert rows["rai1"]["channel"] == {
        "id": "rai1", "name": "Rai 1", "logo": "logos/rai1.png",
        "numbers": {"dtt": 1, "tivusat": 1, "sky": 101}, "sources": ["sky", "tivu"],
    }
    assert rows["rai1"]["programmes"][1]["start"] == "2026-10-12T06:00:00+02:00"
    assert rows["rai1"]["programmes"][1]["source"] == "tivu"
    # Il film della sera finisce il 13: compare in entrambi i giorni.
    next_day = json.loads((api / "guide/2026-10-13.json").read_text())
    assert [p["title"] for r in next_day["channels"] if r["channel"]["id"] == "rai1" for p in r["programmes"]] == ["Film della sera"]

    channel = json.loads((api / "channels/rai1.json").read_text())
    assert len(channel["programmes"]) == 5


@pytest.mark.anyio
async def test_logos_are_cached_between_builds(secret_settings):
    calls: list[str] = []
    await run_build(secret_settings, calls)
    assert "https://services.tivulaguida.it/uploads/channel/rai1hd.png" in calls
    calls.clear()
    await run_build(secret_settings, calls)
    assert "https://services.tivulaguida.it/uploads/channel/rai1hd.png" not in calls


@pytest.mark.anyio
async def test_snapshot_keeps_failed_source(secret_settings):
    await run_build(secret_settings)
    assert load_snapshot(Path(secret_settings.cache_dir)).programmes["rai1"]

    def tivu_down(request: httpx.Request) -> httpx.Response:
        if request.url.host == "services.tivulaguida.it":
            return httpx.Response(503)
        return site_handler()(request)

    health = await run_build(secret_settings, handler=tivu_down)
    assert health["status"] == "degraded"
    tivu = next(s for s in health["sources"] if s["source"] == "tivu")
    assert tivu["error"] and tivu["reused"] >= 1


@pytest.mark.anyio
async def test_nothing_downloaded_keeps_old_site(secret_settings):
    with pytest.raises(RuntimeError, match="nessun programma"):
        await run_build(secret_settings, handler=lambda r: httpx.Response(503))
    assert not Path(secret_settings.out_dir).exists()


@pytest.mark.anyio
async def test_without_token_site_is_at_root(settings):
    await run_build(settings)
    out = Path(settings.out_dir)
    assert (out / "epg.xml.gz").is_file()
    assert (out / "index.html").read_text().count("guide.js") == 1
    # Senza indirizzo pubblico il logo scaricato non ha un URL assoluto per il feed.
    rai1 = next(c for c in ET.fromstring((out / "epg.xml").read_bytes()).iter("channel") if c.get("id") == "rai1")
    assert rai1.find("icon") is None


@pytest.mark.parametrize("token", ["corto", "con/barra-che-non-va-bene", "spazi non ammessi qui"])
def test_bad_token_is_rejected(settings, token):
    with pytest.raises(ValueError, match="SEATV_FEED_TOKEN"):
        dataclasses.replace(settings, feed_token=token).validate()


def test_settings_from_env(monkeypatch):
    from seatv.config import Settings

    monkeypatch.setenv("SEATV_FEED_TOKEN", TOKEN)
    monkeypatch.setenv("SEATV_PUBLIC_URL", "https://seatv.pages.dev/")
    monkeypatch.setenv("SEATV_DAYS_AHEAD", "")
    settings = Settings.from_env()
    assert settings.days_ahead == 7
    assert settings.site_url == f"https://seatv.pages.dev/{TOKEN}"
