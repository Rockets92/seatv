"""Feed XMLTV generico (anche .gz), utile per fonti di terzi o file locali."""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from datetime import date, datetime

import httpx

from seatv.config import ROME
from seatv.sources import SourceChannel, SourceProgramme


def parse_xmltv_time(value: str) -> datetime:
    """Converte "20261012060000 +0200"; senza offset si assume Europe/Rome."""
    value = value.strip()
    stamp, _, offset = value.partition(" ")
    if offset:
        return datetime.strptime(f"{stamp[:14]} {offset}", "%Y%m%d%H%M%S %z")
    return datetime.strptime(stamp[:14], "%Y%m%d%H%M%S").replace(tzinfo=ROME)


def _text(element: ET.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None or not (child.text or "").strip():
        return None
    return child.text.strip()


def parse_xmltv(
    content: bytes, platform: str = "dtt"
) -> tuple[list[SourceChannel], list[SourceProgramme]]:
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    root = ET.fromstring(content)

    channels = []
    for element in root.iter("channel"):
        source_id = element.get("id")
        name = _text(element, "display-name")
        if not source_id or not name:
            continue
        icon = element.find("icon")
        lcn = _text(element, "lcn")
        channels.append(
            SourceChannel(
                source_id=source_id,
                name=name,
                logo=icon.get("src") if icon is not None else None,
                numbers={platform: int(lcn)} if lcn and lcn.isdigit() else {},
            )
        )

    programmes = []
    for element in root.iter("programme"):
        title = _text(element, "title")
        if not title or not element.get("start") or not element.get("stop"):
            continue
        try:
            start = parse_xmltv_time(element.get("start"))
            stop = parse_xmltv_time(element.get("stop"))
        except ValueError:
            continue
        icon = element.find("icon")
        programmes.append(
            SourceProgramme(
                source_channel_id=element.get("channel", ""),
                start=start,
                stop=stop,
                title=title,
                description=_text(element, "desc"),
                category=_text(element, "category"),
                image=icon.get("src") if icon is not None else None,
            )
        )
    return channels, programmes


class XmltvSource:
    name = "xmltv"

    def __init__(self, url: str, platform: str = "dtt") -> None:
        self.url = url
        self.platform = platform
        self._programmes: list[SourceProgramme] = []

    async def fetch_channels(self, client: httpx.AsyncClient) -> list[SourceChannel]:
        response = await client.get(self.url)
        response.raise_for_status()
        channels, self._programmes = parse_xmltv(response.content, self.platform)
        return channels

    async def fetch_programmes(
        self,
        client: httpx.AsyncClient,
        channels: list[SourceChannel],
        days: list[date],
    ) -> list[SourceProgramme]:
        # Il feed è un unico documento, già scaricato da fetch_channels.
        wanted = {c.source_id for c in channels}
        day_set = set(days)
        return [
            p
            for p in self._programmes
            if p.source_channel_id in wanted and p.start.astimezone(ROME).date() in day_set
        ]
