"""Canali che né Tivù né Sky elencano, presi dal feed XMLTV di epgshare01.

L'API della guida Sky non ha Sky Collection (solo Sky Cinema Collection, un
altro canale): il suo palinsesto c'è nel feed italiano di epgshare01. Si
prendono solo i canali in `CHANNELS`, così il resto della guida resta di
Tivù e Sky.
"""

from __future__ import annotations

import gzip
import io
import logging
import xml.etree.ElementTree as ET
from datetime import date

import httpx

from seatv.config import ROME
from seatv.external_ids import EPGSHARE_URLS
from seatv.sources import SourceChannel, SourceProgramme
from seatv.sources.xmltv import parse_xmltv_time

log = logging.getLogger(__name__)

# Id del canale nel feed -> (nome nella guida, numeri per piattaforma).
CHANNELS: dict[str, tuple[str, dict[str, int]]] = {
    "Sky.Collection.it": ("Sky Collection", {"sky": 114}),
}


def _text(element: ET.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None or not (child.text or "").strip():
        return None
    return child.text.strip()


def parse_epgshare(
    content: bytes, wanted: dict[str, tuple[str, dict[str, int]]] = CHANNELS
) -> tuple[list[SourceChannel], list[SourceProgramme]]:
    """Canali e programmi del feed, solo per gli id in `wanted`. Il file è
    grande: si legge un elemento alla volta."""
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    channels: list[SourceChannel] = []
    programmes: list[SourceProgramme] = []
    for _, element in ET.iterparse(io.BytesIO(content), events=("end",)):
        if element.tag == "channel":
            xml_id = element.get("id") or ""
            if xml_id in wanted:
                name, numbers = wanted[xml_id]
                icon = element.find("icon")
                channels.append(
                    SourceChannel(
                        source_id=xml_id,
                        name=name,
                        logo=icon.get("src") if icon is not None and icon.get("src") else None,
                        numbers=dict(numbers),
                    )
                )
            element.clear()
        elif element.tag == "programme":
            title = _text(element, "title")
            if element.get("channel") in wanted and title and element.get("start") and element.get("stop"):
                try:
                    start = parse_xmltv_time(element.get("start"))
                    stop = parse_xmltv_time(element.get("stop"))
                except ValueError:
                    start = stop = None
                if start and stop:
                    icon = element.find("icon")
                    programmes.append(
                        SourceProgramme(
                            source_channel_id=element.get("channel"),
                            start=start,
                            stop=stop,
                            title=title,
                            description=_text(element, "desc"),
                            category=_text(element, "category"),
                            image=icon.get("src") if icon is not None else None,
                        )
                    )
            element.clear()
    return channels, programmes


class EpgshareSource:
    name = "epgshare"

    def __init__(self, urls: tuple[str, ...] = EPGSHARE_URLS) -> None:
        self.urls = urls
        self._programmes: list[SourceProgramme] = []

    async def fetch_channels(self, client: httpx.AsyncClient) -> list[SourceChannel]:
        channels: list[SourceChannel] = []
        self._programmes = []
        for url in self.urls:
            response = await client.get(url, timeout=120)
            response.raise_for_status()
            found, programmes = parse_epgshare(response.content)
            channels += found
            self._programmes += programmes
        missing = set(CHANNELS) - {c.source_id for c in channels}
        if missing:
            log.warning("epgshare: canali non trovati nel feed: %s", ", ".join(sorted(missing)))
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
