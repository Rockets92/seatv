"""Fonti EPG intercambiabili.

Ogni fonte restituisce canali e programmi in un formato comune; l'ingestione
li unisce nel database usando l'id canale normalizzato (vedi `channel_slug`).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

import httpx


@dataclass(frozen=True)
class SourceChannel:
    """Un canale come lo vede una fonte."""

    source_id: str
    name: str
    logo: str | None = None
    # Numerazione per piattaforma: {"dtt": 1, "sat": 101}.
    numbers: dict[str, int] = field(default_factory=dict)

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


_HD_SUFFIX = re.compile(r"\s+hd$", re.IGNORECASE)


def clean_name(name: str) -> str:
    """Nome da mostrare: "Rai 1 HD" -> "Rai 1"."""
    return _HD_SUFFIX.sub("", name.strip())


def channel_slug(name: str) -> str:
    """Id canale stabile: "Rai 1 HD" -> "rai-1", "Real time HD" -> "real-time".

    Il suffisso HD viene tolto perché le fonti elencano spesso la versione SD e
    quella HD dello stesso canale, che hanno lo stesso palinsesto.
    """
    name = unicodedata.normalize("NFKD", clean_name(name)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
