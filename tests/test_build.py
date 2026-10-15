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
    assert f"/{TOKEN}/*.xml.gz\n  Content-Type: application/gzip" in headers

    for name in ["index.html", "epg.xml", "epg.xml.gz", "static/guide.js", "static/guide.css", "static/logo.png",
                 "api/health.json", "api/channels.json", "api/channels/rai1.json",
                 "api/guide/2026-10-12.json", "api/guide/2026-10-13.json", "logos/rai1.png"]:
        assert (site / name).is_file(), name
    # La pagina usa solo indirizzi relativi, così funziona sotto /<token>/.
    page = (site / "index.html").read_text()
    assert 'src="/' not in page and 'href="/' not in page

    assert health["status"] == "ok"
    assert health["days"] == ["2026-10-12", "2026-10-13"]
    assert health["feeds"] == [{"scheme": "seatv", "gz": "epg.xml.gz", "xml": "epg.xml", "channels": 7}]
    assert json.loads((site / "api/health.json").read_text()) == health


@pytest.mark.anyio
async def test_installable_app(secret_settings):
    """La guida si installa come app: manifest, icone e service worker sotto il token."""
    await run_build(secret_settings)
    out = Path(secret_settings.out_dir)
    site = out / TOKEN

    manifest = json.loads((site / "manifest.webmanifest").read_text())
    assert manifest["display"] == "fullscreen"
    assert manifest["start_url"] == manifest["scope"] == "./"
    for icon in manifest["icons"]:
        assert (site / icon["src"]).is_file(), icon["src"]
    assert {i["sizes"] for i in manifest["icons"]} >= {"192x192", "512x512"}
    assert any(i["purpose"] == "maskable" for i in manifest["icons"])

    worker = (site / "sw.js").read_text()
    assert "__BUILD__" not in worker
    assert 'const VERSION = "20261012' in worker

    page = (site / "index.html").read_text()
    assert '<link rel="manifest" href="manifest.webmanifest">' in page
    assert 'href="guida-api.html"' in page and "Guida API" in page

    # La Guida API è nel sito, con tabelle, esempi e l'indirizzo vero al posto del segnaposto.
    docs = (site / "guida-api.html").read_text()
    assert '<h2 id="api">Guida API</h2>' in docs
    assert "<table>" in docs and "<pre><code>" in docs
    assert "api/guide/{AAAA-MM-GG}.json" in docs
    assert f"https://seatv.pages.dev/{TOKEN}/api/channels.json" in docs
    assert "&lt;token&gt;" not in docs
    assert 'name="apple-mobile-web-app-capable" content="yes"' in page

    headers = (out / "_headers").read_text()
    assert f"/{TOKEN}/sw.js\n  Cache-Control: no-cache" in headers
    assert f"/{TOKEN}/manifest.webmanifest\n  Content-Type: application/manifest+json" in headers


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
        "numbers": {"dtt": 1, "tivusat": 1, "sky": 101}, "sources": ["sky", "tivu"], "ids": {},
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


IPTV_ORG_CHANNELS = """id,name,alt_names,network,owners,country,categories,is_nsfw,launched,closed,replaced_by,website
Rai1.it,Rai 1,Rai Uno;TV1,,Rai,IT,,FALSE,,,,
SkyUno.it,Sky Uno,,,,IT,,FALSE,,,,
SkyTG24.it,Sky TG24,,,,IT,news,FALSE,,2016-02-23,,
TV1.it,TV1,,,,IT,,FALSE,,,,
Rai1.ch,Rai 1,,,,CH,,FALSE,,,,
"""
IPTV_ORG_FEEDS = """channel,id,name,alt_names,is_main,broadcast_area,timezones,languages,format
Rai1.it,SD,SD,,TRUE,c/IT,Europe/Rome,ita,576i
Rai1.it,HD,HD,,FALSE,c/IT,Europe/Rome,ita,1080i
SkyUno.it,SD,SD,,TRUE,c/IT,Europe/Rome,ita,576i
SkyUno.it,Plus1,+1,,FALSE,c/IT,Europe/Rome,ita,576i
SkyUno.it,Plus1HD,+1 HD,,FALSE,c/IT,Europe/Rome,ita,1080i
SkyUno.it,West,West,,FALSE,c/IT,Europe/Rome,ita,576i
"""
EPGSHARE = b"""<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="Rai.1.HD.it"><display-name>Rai 1 HD</display-name></channel>
  <channel id="Rai.2.HD..102.it"><display-name>Rai 2 HD (102)</display-name></channel>
  <channel id="La.5.it"/>
  <channel id="Canale.5.it"><display-name lang="it">Canale 5</display-name></channel>
  <programme start="20261012060000 +0200" stop="20261012070000 +0200" channel="Rai.1.HD.it"><title>X</title></programme>
</tv>
"""


def test_iptv_org_ids():
    from seatv.external_ids import parse_iptv_org

    ids = parse_iptv_org(IPTV_ORG_CHANNELS, IPTV_ORG_FEEDS)
    assert ids["rai1"] == ["Rai1.it", "Rai1.it@SD", "Rai1.it@HD"]
    assert ids["skyuno"] == ["SkyUno.it", "SkyUno.it@SD"]
    # Le varianti +1 vanno al canale +1; quelle regionali si ignorano.
    assert ids["skyunoplus1"] == ["SkyUno.it@Plus1", "SkyUno.it@Plus1HD"]
    # "TV1" è anche un nome alternativo di Rai 1, ma il nome principale vince.
    assert ids["tv1"] == ["TV1.it"]
    # Un canale segnato come chiuso si abbina lo stesso: le date di iptv-org non sono affidabili.
    assert ids["skytg24"] == ["SkyTG24.it"]


def test_epgshare_ids():
    import gzip as gz

    from seatv.external_ids import parse_xmltv_ids

    ids = parse_xmltv_ids(gz.compress(EPGSHARE))
    assert ids["rai1"] == ["Rai.1.HD.it"]
    assert ids["rai2"] == ["Rai.2.HD..102.it"]
    # Senza display-name il nome si ricava dall'id.
    assert ids["la5"] == ["La.5.it"]
    assert ids["canale5"] == ["Canale.5.it"]


@pytest.mark.anyio
async def test_compatible_feeds(secret_settings):
    settings = dataclasses.replace(secret_settings, external_ids=("iptvorg", "epgshare"))
    base = site_handler()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("channels.csv"):
            return httpx.Response(200, text=IPTV_ORG_CHANNELS)
        if request.url.path.endswith("feeds.csv"):
            return httpx.Response(200, text=IPTV_ORG_FEEDS)
        if request.url.host == "epgshare01.online":
            return httpx.Response(200, content=EPGSHARE)
        return base(request)

    health = await run_build(settings, handler=handler)
    site = Path(settings.out_dir) / TOKEN
    assert [(f["scheme"], f["gz"], f["channels"]) for f in health["feeds"]] == [
        ("seatv", "epg.xml.gz", 7),
        ("iptvorg", "epg-iptvorg.xml.gz", 4),
        ("epgshare", "epg-epgshare.xml.gz", 2),
    ]

    root = ET.fromstring(gzip.decompress((site / "epg-iptvorg.xml.gz").read_bytes()))
    channel_ids = [c.get("id") for c in root.iter("channel")]
    # Rai 1 con tutti i suoi id iptv-org; un canale senza corrispondenza tiene il nostro id.
    assert channel_ids[:4] == ["Rai1.it", "Rai1.it@SD", "Rai1.it@HD", "canale5"]
    assert "SkyUno.it@Plus1" in channel_ids
    # Il palinsesto si ripete per ogni id.
    titles = [p.findtext("title") for p in root.iter("programme") if p.get("channel") == "Rai1.it@HD"]
    assert titles == ["Speciale notte", "Tg1", "Unomattina", "Tg1", "Film della sera"]

    epgshare = ET.fromstring((site / "epg-epgshare.xml").read_bytes())
    assert [c.get("id") for c in epgshare.iter("channel")][:2] == ["Rai.1.HD.it", "Canale.5.it"]

    rai1 = json.loads((site / "api/channels/rai1.json").read_text())["channel"]
    assert rai1["ids"] == {"iptvorg": ["Rai1.it", "Rai1.it@SD", "Rai1.it@HD"], "epgshare": ["Rai.1.HD.it"]}

    # Se il giorno dopo le liste non si scaricano, si usano gli id dell'ultima volta.
    def lists_down(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".csv") or request.url.host == "epgshare01.online":
            return httpx.Response(503)
        return base(request)

    health = await run_build(settings, handler=lists_down)
    assert [f["channels"] for f in health["feeds"]] == [7, 4, 2]
