"""Sito statico da pubblicare su Cloudflare Pages (o qualsiasi hosting di file).

Struttura, con il token nel percorso:

    /                         pagina vuota, nessun dato
    /<token>/                 guida TV web
    /<token>/epg.xml          feed XMLTV (e epg.xml.gz compresso)
    /<token>/api/...          API JSON in file statici
    /<token>/logos/<id>.png   loghi dei canali

Il token è l'unica protezione: chi non lo conosce non trova nulla, e i
motori di ricerca sono tenuti fuori (robots.txt e X-Robots-Tag).
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import date, datetime, time, timedelta
from pathlib import Path

from seatv.config import ROME, Settings
from seatv.export.docs import render_docs
from seatv.export.xmltv import gzip_bytes, render_xmltv
from seatv.model import Guide, Programme

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
WEB_ASSETS = (
    "guide.css", "guide.js", "logo.png", "favicon.ico",
    "icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png",
)
# Cloudflare Pages non pubblica file più grandi di 25 MiB.
MAX_FILE_BYTES = 25 * 1024 * 1024

ROOT_PAGE = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>SEA-TV</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#020817;color:#64748b;font:16px system-ui,sans-serif}</style>
</head>
<body><p>SEA-TV</p></body>
</html>
"""

ROBOTS = "User-agent: *\nDisallow: /\n"


def headers_file(prefix: str) -> str:
    """Intestazioni HTTP per Cloudflare Pages (file `_headers`)."""
    base = f"/{prefix}" if prefix else ""
    return f"""/*
  X-Robots-Tag: noindex, nofollow
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff

{base}/*.xml
  Content-Type: application/xml; charset=utf-8
  Cache-Control: public, max-age=900
  Access-Control-Allow-Origin: *

{base}/*.xml.gz
  Content-Type: application/gzip
  Cache-Control: public, max-age=900
  Access-Control-Allow-Origin: *

{base}/api/*
  Cache-Control: public, max-age=300
  Access-Control-Allow-Origin: *

{base}/logos/*
  Cache-Control: public, max-age=86400

{base}/sw.js
  Cache-Control: no-cache

{base}/manifest.webmanifest
  Content-Type: application/manifest+json
  Cache-Control: no-cache
"""


def _rome(value: datetime) -> str:
    return value.astimezone(ROME).isoformat()


def _programme(p: Programme) -> dict:
    return {
        "start": _rome(p.start),
        "stop": _rome(p.stop),
        "title": p.title,
        "description": p.description,
        "category": p.category,
        "image": p.image,
        "source": p.source,
    }


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _write_feed(site: Path, stem: str, xml: bytes, scheme: str, matched: int) -> dict:
    """Scrive <stem>.xml.gz e, se sta nel limite di Cloudflare, <stem>.xml."""
    gz = gzip_bytes(xml)
    if len(gz) > MAX_FILE_BYTES:
        raise RuntimeError(f"{stem}.xml.gz è di {len(gz) / 1e6:.1f} MB, oltre il limite di 25 MiB di Cloudflare Pages")
    (site / f"{stem}.xml.gz").write_bytes(gz)
    feed = {"scheme": scheme, "gz": f"{stem}.xml.gz", "xml": None, "channels": matched}
    if len(xml) <= MAX_FILE_BYTES:
        (site / f"{stem}.xml").write_bytes(xml)
        feed["xml"] = f"{stem}.xml"
    else:
        log.warning("%s.xml è di %.1f MB, oltre il limite di Cloudflare Pages: si pubblica solo %s.xml.gz", stem, len(xml) / 1e6, stem)
    log.info("feed %s: %.1f MB (compresso %.1f MB), %d canali con i suoi id", stem, len(xml) / 1e6, len(gz) / 1e6, matched)
    return feed


def guide_dates(guide: Guide) -> list[date]:
    """Giorni (ora italiana) che hanno almeno un programma."""
    days = set()
    for rows in guide.programmes.values():
        for p in rows:
            days.add(p.start.astimezone(ROME).date())
    return sorted(days)


def write_site(guide: Guide, settings: Settings, days: list[date]) -> dict:
    """Scrive il sito in `settings.out_dir` e restituisce i dati di /api/health.json."""
    out = Path(settings.out_dir)
    if out.exists():
        shutil.rmtree(out)
    site = out / settings.feed_token if settings.feed_token else out
    site.mkdir(parents=True)

    def logo_url(logo: str | None) -> str | None:
        """Indirizzo assoluto del logo per il feed XMLTV."""
        if not logo or logo.startswith(("https://", "http://")):
            return logo
        return f"{settings.site_url}/{logo}" if settings.site_url else None

    # Feed XMLTV: con gli id SEA-TV e, per ogni lista IPTV nota, con i suoi id.
    feeds = [_write_feed(site, "epg", render_xmltv(guide, logo_url), "seatv", len(guide.channels))]
    for scheme in settings.external_ids:
        def ids(channel, scheme=scheme):
            return channel.external.get(scheme) or [channel.id]

        matched = sum(1 for c in guide.channels.values() if c.external.get(scheme))
        feeds.append(_write_feed(site, f"epg-{scheme}", render_xmltv(guide, logo_url, ids), scheme, matched))

    # API JSON.
    api = site / "api"
    channels = guide.sorted_channels()
    _write_json(api / "channels.json", [c.public() for c in channels])
    for channel in channels:
        _write_json(
            api / "channels" / f"{channel.id}.json",
            {"channel": channel.public(), "programmes": [_programme(p) for p in guide.programmes.get(channel.id, [])]},
        )
    for day in days:
        start = datetime.combine(day, time.min, tzinfo=ROME)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=ROME)
        _write_json(
            api / "guide" / f"{day.isoformat()}.json",
            {
                "date": day.isoformat(),
                "channels": [
                    {"channel": c.public(), "programmes": [_programme(p) for p in guide.overlapping(c.id, start, end)]}
                    for c in channels
                ],
            },
        )
    failed = [run for run in guide.runs if run.error]
    health = {
        "status": "ok" if guide.runs and not failed else "degraded",
        "generated_at": _rome(guide.generated_at),
        "days": [d.isoformat() for d in days],
        "channels": len(channels),
        "programmes": guide.programme_count,
        "feeds": feeds,
        "sources": [
            {
                "source": run.source,
                "started_at": _rome(run.started_at),
                "finished_at": _rome(run.finished_at) if run.finished_at else None,
                "channels": run.channels,
                "programmes": run.programmes,
                "reused": run.reused,
                "error": run.error,
            }
            for run in guide.runs
        ],
    }
    _write_json(api / "health.json", health)

    # Pagina web.
    (site / "static").mkdir()
    for name in WEB_ASSETS:
        shutil.copyfile(WEB_DIR / name, site / "static" / name)
    shutil.copyfile(WEB_DIR / "index.html", site / "index.html")
    # Guida d'uso (README e docs/cloudflare.md), raggiungibile dalla pagina.
    (site / "guida.html").write_text(render_docs(), encoding="utf-8")
    # App installabile: manifest e service worker stanno nella cartella della
    # guida, così valgono per tutto ciò che c'è sotto il token.
    shutil.copyfile(WEB_DIR / "manifest.webmanifest", site / "manifest.webmanifest")
    # La versione nel service worker cambia a ogni aggiornamento: l'app
    # installata scarica pagina e stili nuovi al primo avvio successivo.
    worker = (WEB_DIR / "sw.js").read_text(encoding="utf-8")
    (site / "sw.js").write_text(worker.replace("__BUILD__", guide.generated_at.strftime("%Y%m%d%H%M%S")), encoding="utf-8")
    shutil.copyfile(WEB_DIR / "favicon.ico", out / "favicon.ico")

    # Radice e regole per Cloudflare Pages. Senza 404.html Pages risponderebbe
    # con la pagina principale a qualsiasi indirizzo.
    if settings.feed_token:
        (out / "index.html").write_text(ROOT_PAGE, encoding="utf-8")
    (out / "404.html").write_text(ROOT_PAGE, encoding="utf-8")
    (out / "robots.txt").write_text(ROBOTS, encoding="utf-8")
    (out / "_headers").write_text(headers_file(settings.feed_token), encoding="utf-8")
    return health


def copy_logos(logos: dict[str, Path], site: Path) -> dict[str, str]:
    """Copia i loghi scaricati nel sito; restituisce il percorso pubblicato per canale."""
    published = {}
    target = site / "logos"
    target.mkdir(parents=True, exist_ok=True)
    for channel_id, path in logos.items():
        name = f"{channel_id}{path.suffix}"
        shutil.copyfile(path, target / name)
        published[channel_id] = f"logos/{name}"
    return published
