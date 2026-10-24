"""Tivù La Guida (services.tivulaguida.it): DTT nazionale e Tivùsat.

Endpoint e formato ricavati dal grabber `sites/tivu.tv` di iptv-org/epg.
L'API riporta anche la numerazione: `channel_dtt` (DTT) e `channel_sat` (Tivùsat).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

import httpx

from seatv.config import ROME
from seatv.sources import EPISODE_ONLY, SourceChannel, SourceProgramme, fetch_each_day

BASE_URL = "https://services.tivulaguida.it"
TIME_FORMAT = "%d-%m-%Y %H:%M"

log = logging.getLogger(__name__)
# Diagnosi: esempi di eventi con il solo episodio nel titolo.
SAMPLES: list[dict] = []


def parse_channels(payload: dict, base_url: str = BASE_URL) -> list[SourceChannel]:
    channels = []
    for item in payload.get("channels") or []:
        numbers = {}
        if item.get("is_dtt") and item.get("channel_dtt"):
            numbers["dtt"] = int(item["channel_dtt"])
        if item.get("is_sat") and item.get("channel_sat"):
            numbers["tivusat"] = int(item["channel_sat"])
        icon = item.get("icon")
        channels.append(
            SourceChannel(
                source_id=str(item["id"]),
                name=item["name"].strip(),
                logo=f"{base_url}/{icon}" if icon else None,
                numbers=numbers,
            )
        )
    return channels


def parse_events(payload: dict, source_channel_id: str) -> list[SourceProgramme]:
    programmes = []
    for event in payload.get("events") or []:
        program = event.get("program")
        if not program or not program.get("title"):
            continue
        try:
            start = datetime.strptime(event["date_start"], TIME_FORMAT).replace(tzinfo=ROME)
            stop = datetime.strptime(event["date_end"], TIME_FORMAT).replace(tzinfo=ROME)
        except (KeyError, ValueError):
            continue
        if EPISODE_ONLY.fullmatch(program["title"].strip()) and len(SAMPLES) < 3:
            SAMPLES.append(event)
        categories = program.get("categories") or []
        programmes.append(
            SourceProgramme(
                source_channel_id=source_channel_id,
                start=start,
                stop=stop,
                title=program["title"].strip(),
                description=(program.get("description") or "").strip() or None,
                category=categories[0].get("name") if categories else None,
                image=program.get("url_poster") or None,
            )
        )
    return programmes


class TivuSource:
    name = "tivu"

    def __init__(self, concurrency: int = 4, base_url: str = BASE_URL) -> None:
        self.concurrency = concurrency
        self.base_url = base_url.rstrip("/")

    async def fetch_channels(self, client: httpx.AsyncClient) -> list[SourceChannel]:
        response = await client.get(f"{self.base_url}/api/epg/channels.json")
        response.raise_for_status()
        return parse_channels(response.json(), self.base_url)

    async def fetch_programmes(
        self,
        client: httpx.AsyncClient,
        channels: list[SourceChannel],
        days: list[date],
    ) -> list[SourceProgramme]:
        async def fetch(channel: SourceChannel, day: date) -> list[SourceProgramme]:
            url = f"{self.base_url}/api/epg/channels/{channel.source_id}/date/{day.isoformat()}"
            response = await client.get(url)
            response.raise_for_status()
            return parse_events(response.json(), channel.source_id)

        programmes = await fetch_each_day(self.name, channels, days, self.concurrency, fetch)
        bare = [p.title for p in programmes if EPISODE_ONLY.fullmatch(p.title)]
        if bare:
            log.warning("tivu: %d titoli con il solo episodio (es. %s)", len(bare), bare[:3])
            for event in SAMPLES:
                log.warning("tivu: esempio %s", json.dumps(event, ensure_ascii=False)[:2500])
        return programmes
