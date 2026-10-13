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
    """Indirizzi dei loghi per id SEA-TV (`skyuno`, `skyunoplus1`).

    Si usano i canali italiani; un canale che manca tra gli italiani prende
    il logo di un altro paese solo se il nome esiste in un paese soltanto
    (es. `DAZN3.uk`, stesso marchio), così "Sport TV" non prende il logo di
    un omonimo straniero."""
    italian: dict[str, list[str]] = {}
    foreign: dict[str, dict[str, list[str]]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        name, _, country = (row.get("channel") or "").rpartition(".")
        feed = row.get("feed") or ""
        url = row.get("url") or ""
        if (
            not name
            or feed not in FEEDS
            or (row.get("format") or "").upper() not in FORMATS
            or (row.get("in_use") or "").upper() != "TRUE"
            or not url.startswith("https://")
        ):
            continue
        slug = channel_slug(name + FEEDS[feed])
        if not slug:
            continue
        urls = italian.setdefault(slug, []) if country == "it" else foreign.setdefault(slug, {}).setdefault(country, [])
        if url not in urls:
            urls.append(url)
    for slug, countries in foreign.items():
        if slug not in italian and len(countries) == 1:
            italian[slug] = next(iter(countries.values()))
    return italian


async def fetch(client: httpx.AsyncClient, url: str = URL) -> dict[str, list[str]]:
    response = await client.get(url)
    response.raise_for_status()
    return parse(response.text)
