"""Loghi di riserva dal database pubblico di iptv-org (dominio pubblico).

Servono per i canali il cui logo non si scarica dalla fonte del palinsesto.
Il file elenca, per ogni canale (es. `SkyUno.it`), uno o più indirizzi di
immagini, quasi tutte su Wikimedia o Imgur.
"""

from __future__ import annotations

import csv
import io
import logging

import httpx

from seatv.sources import channel_slug

log = logging.getLogger(__name__)

URL = "https://raw.githubusercontent.com/iptv-org/database/master/data/logos.csv"
FORMATS = {"PNG", "JPEG", "GIF", "WEBP"}
# Varianti di iptv-org che corrispondono ai nostri canali: HD e SD sono lo stesso canale.
FEEDS = {"": "", "HD": "", "SD": "", "Plus1": " +1", "Plus24": " +24"}


def parse(text: str) -> dict[str, list[str]]:
    """Indirizzi dei loghi dei canali italiani per id SEA-TV (`skyuno`, `skyunoplus1`)."""
    logos: dict[str, list[str]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        name, _, country = (row.get("channel") or "").rpartition(".")
        feed = row.get("feed") or ""
        url = row.get("url") or ""
        if (
            country != "it"
            or feed not in FEEDS
            or (row.get("format") or "").upper() not in FORMATS
            or (row.get("in_use") or "").upper() != "TRUE"
            or not url.startswith("https://")
        ):
            continue
        slug = channel_slug(name + FEEDS[feed])
        if slug and url not in logos.setdefault(slug, []):
            logos[slug].append(url)
    return logos


async def fetch(client: httpx.AsyncClient, url: str = URL) -> dict[str, list[str]]:
    response = await client.get(url)
    response.raise_for_status()
    return parse(response.text)
