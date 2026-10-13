"""Fonti EPG intercambiabili.

Ogni fonte restituisce canali e programmi in un formato comune; l'ingestione
li unisce nel database usando l'id canale normalizzato (vedi `channel_slug`).
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Awaitable, Callable, Protocol

import httpx

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceChannel:
    """Un canale come lo vede una fonte."""

    source_id: str
    name: str
    logo: str | None = None
    # Altri loghi da provare se `logo` non si scarica (es. varianti chiare/scure).
    alt_logos: tuple[str, ...] = ()
    # Numerazione per piattaforma: {"dtt": 1, "tivusat": 1, "sky": 101}.
    numbers: dict[str, int] = field(default_factory=dict)

    @property
    def logos(self) -> list[str]:
        return [url for url in (self.logo, *self.alt_logos) if url]

    @property
    def channel_id(self) -> str:
        return channel_slug(self.name)


@dataclass(frozen=True)
class SourceProgramme:
    source_channel_id: str
    start: datetime  # timezone-aware
    stop: datetime  # timezone-aware
    title: str
    description: str | None = None
    category: str | None = None
    image: str | None = None


class Source(Protocol):
    name: str

    async def fetch_channels(self, client: httpx.AsyncClient) -> list[SourceChannel]: ...

    async def fetch_programmes(
        self,
        client: httpx.AsyncClient,
        channels: list[SourceChannel],
        days: list[date],
    ) -> list[SourceProgramme]: ...


_HD = re.compile(r"\s*\bhd\b", re.IGNORECASE)

# Nomi che le fonti scrivono in modo diverso per lo stesso canale.
ALIASES = {
    "mediasetitalia2": "italia2",
    "la7d": "la7cinema",
}


def clean_name(name: str) -> str:
    """Nome da mostrare: "Rai 1 HD" -> "Rai 1"."""
    return re.sub(r"\s+", " ", _HD.sub("", name)).strip()


def channel_slug(name: str) -> str:
    """Id canale stabile, uguale tra le fonti.

    "Rai 1 HD" -> "rai1", "20 Mediaset HD" e "20Mediaset HD" -> "20mediaset",
    "Sky Uno +1" -> "skyunoplus1". La sigla HD viene tolta perché le fonti
    elencano spesso la versione SD e quella HD dello stesso canale, che hanno
    lo stesso palinsesto.
    """
    name = clean_name(name).replace("+", " plus ")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "", name.lower())
    return ALIASES.get(slug, slug)


async def fetch_each_day(
    source: str,
    channels: list[SourceChannel],
    days: list[date],
    concurrency: int,
    fetch: Callable[[SourceChannel, date], Awaitable[list[SourceProgramme]]],
) -> list[SourceProgramme]:
    """Chiama `fetch` per ogni canale e giorno, con un limite di richieste in
    parallelo. Un canale o un giorno che fallisce viene saltato e registrato."""
    semaphore = asyncio.Semaphore(concurrency)

    async def one(channel: SourceChannel, day: date) -> list[SourceProgramme]:
        async with semaphore:
            try:
                return await fetch(channel, day)
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                log.warning("%s: %s (%s) %s non scaricato: %s", source, channel.name, channel.source_id, day, exc)
                return []

    results = await asyncio.gather(*(one(c, d) for c in channels for d in days))
    return [p for batch in results for p in batch]
