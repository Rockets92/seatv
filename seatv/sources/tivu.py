"""Tivù La Guida (services.tivulaguida.it): DTT nazionale e Tivùsat.

Endpoint e formato ricavati dal grabber `sites/tivu.tv` di iptv-org/epg.
L'API riporta anche la numerazione: `channel_dtt` (DTT) e `channel_sat` (Tivùsat).
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

from seatv.config import ROME
from seatv.sources import SourceChannel, SourceProgramme, fetch_each_day

BASE_URL = "https://services.tivulaguida.it"
TIME_FORMAT = "%d-%m-%Y %H:%M"


def parse_channels(payload: dict) -> list[SourceChannel]:
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
                logo=f"{BASE_URL}/{icon}" if icon else None,
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

    def __init__(self, concurrency: int = 4) -> None:
        self.concurrency = concurrency

    async def fetch_channels(self, client: httpx.AsyncClient) -> list[SourceChannel]:
        response = await client.get(f"{BASE_URL}/api/epg/channels.json")
        response.raise_for_status()
        return parse_channels(response.json())

    async def fetch_programmes(
        self,
        client: httpx.AsyncClient,
        channels: list[SourceChannel],
        days: list[date],
    ) -> list[SourceProgramme]:
        async def fetch(channel: SourceChannel, day: date) -> list[SourceProgramme]:
            url = f"{BASE_URL}/api/epg/channels/{channel.source_id}/date/{day.isoformat()}"
            response = await client.get(url)
            response.raise_for_status()
            return parse_events(response.json(), channel.source_id)

        return await fetch_each_day(self.name, channels, days, self.concurrency, fetch)
