"""Sky Guida TV (apid.sky.it/gtv/v1): piattaforma satellitare Sky Italia.

Endpoint e formato ricavati dal grabber `sites/guidatv.sky.it` di iptv-org/epg.
I numeri restituiti sono quelli del decoder Sky (es. Rai 1 = 101).
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, timezone

import httpx

from seatv.config import ROME
from seatv.sources import SourceChannel, SourceProgramme, fetch_each_day

API_URL = "https://apid.sky.it/gtv/v1"
SITE_URL = "https://guidatv.sky.it"
# guidatv.sky.it ora rimanda a programmi.sky.it: i loghi si cercano su entrambi.
LOGO_HOSTS = ("https://programmi.sky.it", SITE_URL)
# DTH = satellite.
ENV = "DTH"
LOGO_KEYS = ("logo", "logoPadding", "logoLight", "logoDark", "logoDarkPadding")
# Titoli che sono solo il numero dell'episodio: "Ep. 3", "S2 Ep. 3", "Episodio 12".
EPISODE_ONLY = re.compile(r"(?i)(s(t(agione)?)?\.?\s*\d+\s*[-,]?\s*)?(ep(isodio)?\.?\s*\d+)(\s*[-:–].*)?")

log = logging.getLogger(__name__)
_EPISODE_PREFIX = re.compile(r"(?i)^\s*(s\d+\s*)?ep\.?\s*\d+\s*[-–:]\s*")
_SHOW_URL = re.compile(r"^/programmi-tv/[^/]+/([^/]+)/(stagione|episodio)-")


def series_name(event: dict) -> str | None:
    """Nome della serie di un episodio. Sky lo mette in `epgEventTitle`
    ("S15 Ep15 - MasterChef USA"); in mancanza si prova `content.contentTitle`
    e poi l'indirizzo della scheda (/programmi-tv/show/masterchef-usa/...)."""
    content = event.get("content") or {}
    epg = (event.get("epgEventTitle") or "").strip()
    if epg and _EPISODE_PREFIX.match(epg):
        name = _EPISODE_PREFIX.sub("", epg).strip()
        if name and not EPISODE_ONLY.fullmatch(name):
            return name
    series = (content.get("contentTitle") or "").strip()
    if series and not EPISODE_ONLY.fullmatch(series):
        return series
    m = _SHOW_URL.match(content.get("url") or "")
    if m:
        return m[1].replace("-", " ").title()
    return None


def event_title(event: dict) -> str:
    """Titolo del programma. Per molte serie Sky mette in `eventTitle` solo
    l'episodio ("Ep. 3"): allora il titolo diventa "Nome della serie - Ep. 3"."""
    title = (event.get("eventTitle") or "").strip()
    if EPISODE_ONLY.fullmatch(title):
        series = series_name(event)
        if series and series.lower() not in title.lower():
            return f"{series} - {title}"
    return title


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_channels(payload: dict) -> list[SourceChannel]:
    channels = []
    for item in payload.get("channels") or []:
        if not item.get("id") or not item.get("name"):
            continue
        number = item.get("number")
        # Sky dà lo stesso logo in più versioni; si prova prima quella per sfondi chiari.
        logos = list(dict.fromkeys(
            f"{host}{item[key]}"
            for key in LOGO_KEYS
            if isinstance(item.get(key), str) and item[key]
            for host in LOGO_HOSTS
        ))
        channels.append(
            SourceChannel(
                source_id=str(item["id"]),
                name=item["name"].strip(),
                # Percorso relativo sullo stesso host delle immagini dei programmi.
                logo=logos[0] if logos else None,
                alt_logos=tuple(logos[1:]),
                numbers={"sky": int(number)} if number else {},
            )
        )
    return channels


def parse_events(payload: dict, source_channel_id: str) -> list[SourceProgramme]:
    programmes = []
    for event in payload.get("events") or []:
        title = event_title(event)
        if not title or not event.get("starttime") or not event.get("endtime"):
            continue
        try:
            start = _parse_time(event["starttime"])
            stop = _parse_time(event["endtime"])
        except ValueError:
            continue
        content = event.get("content") or {}
        genre = (content.get("genre") or {}).get("name")
        subgenre = (content.get("subgenre") or {}).get("name")
        cover = next(
            (i.get("img", {}).get("url") for i in content.get("imagesMap") or [] if i.get("key") == "cover"),
            None,
        )
        programmes.append(
            SourceProgramme(
                source_channel_id=source_channel_id,
                start=start,
                stop=stop,
                title=title,
                description=(event.get("eventSynopsis") or "").strip() or None,
                category=f"{genre}/{subgenre}" if genre and subgenre else genre,
                image=f"{SITE_URL}{cover}" if cover else None,
            )
        )
    return programmes


class SkySource:
    name = "sky"

    def __init__(self, concurrency: int = 4) -> None:
        self.concurrency = concurrency

    async def fetch_channels(self, client: httpx.AsyncClient) -> list[SourceChannel]:
        response = await client.get(f"{API_URL}/channels", params={"env": ENV})
        response.raise_for_status()
        return parse_channels(response.json())

    async def fetch_programmes(
        self,
        client: httpx.AsyncClient,
        channels: list[SourceChannel],
        days: list[date],
    ) -> list[SourceProgramme]:
        async def fetch(channel: SourceChannel, day: date) -> list[SourceProgramme]:
            # Il giorno va da mezzanotte a mezzanotte, ora italiana.
            start = datetime.combine(day, time.min, tzinfo=ROME)
            end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=ROME)
            response = await client.get(
                f"{API_URL}/events",
                params={
                    "from": _utc(start),
                    "to": _utc(end),
                    "pageSize": 999,
                    "pageNum": 0,
                    "env": ENV,
                    "channels": channel.source_id,
                },
            )
            response.raise_for_status()
            return parse_events(response.json(), channel.source_id)

        programmes = await fetch_each_day(self.name, channels, days, self.concurrency, fetch)
        bare = [p.title for p in programmes if EPISODE_ONLY.fullmatch(p.title)]
        if bare:
            log.warning("sky: %d titoli con il solo episodio, senza nome della serie (es. %s)", len(bare), bare[:3])
        return programmes
