"""Id dei canali usati dalle liste IPTV più diffuse, per i feed compatibili.

I programmi IPTV abbinano il `tvg-id` della playlist all'id del canale nel
feed XMLTV, e le liste in circolazione usano schemi diversi dal nostro
(`rai1`):

- iptv-org (database pubblico e playlist di iptv-org/iptv): `Rai2.it`,
  `Rai2.it@SD`, `Rai2.it@HD`, `SkyUno.it@Plus1`.
- epgshare01 e le liste costruite sui suoi feed: `Rai.2.HD.it`, `La.5.it`.
  Gli id si leggono dal loro feed XMLTV italiano.

Ogni schema dà, per id SEA-TV, l'elenco degli id esterni equivalenti. Gli
abbinamenti si fanno per nome normalizzato, come tra le nostre fonti.
"""

from __future__ import annotations

import csv
import gzip
import io
import logging
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

import httpx

from seatv.sources import channel_slug

log = logging.getLogger(__name__)

IPTV_ORG_CHANNELS = "https://raw.githubusercontent.com/iptv-org/database/master/data/channels.csv"
IPTV_ORG_FEEDS = "https://raw.githubusercontent.com/iptv-org/database/master/data/feeds.csv"
EPGSHARE_URLS = ("https://epgshare01.online/epgshare01/epg_ripper_IT1.xml.gz",)

# Varianti iptv-org che sono lo stesso canale (SD/HD) o un nostro canale +1/+24.
_FEED_NAME = re.compile(r"(SD|HD|\+\d+(\s*HD)?)", re.IGNORECASE)


def external_slug(name: str) -> str:
    """Come `channel_slug`, ignorando le parti tra parentesi: "Rai 2 HD (102)" -> "rai2"."""
    return channel_slug(re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", name))


# Nomi con cui le liste chiamano alcuni nostri canali.
SYNONYMS = {
    "discovery": ("discoverychannel",),
    "tgcom24": ("tgcom",),
    "20mediaset": ("20",),
    "giallo": ("giallotv",),
    "hgtvitaly": ("hgtv",),
}
_SUFFIXES = ("channel", "tv", "italia", "italy")


def external_candidates(channel_id: str) -> list[str]:
    """Slug da cercare in una lista per un nostro canale, il suo id per primo:
    poi i sinonimi e le varianti con o senza "channel", "tv", "italia"
    ("discovery" -> "discoverychannel", "hgtvitaly" -> "hgtv")."""
    names = [channel_id, *SYNONYMS.get(channel_id, ())]
    for name in list(names):
        for suffix in _SUFFIXES:
            if name.endswith(suffix) and len(name) > len(suffix) + 1:
                names.append(name[: -len(suffix)])
            else:
                names.append(name + suffix)
    return list(dict.fromkeys(names))


def parse_iptv_org(channels_csv: str, feeds_csv: str) -> dict[str, list[str]]:
    """Id iptv-org per id SEA-TV: il canale (`Rai2.it`) e le sue varianti
    SD/HD (`Rai2.it@SD`); i +1 (`SkyUno.it@Plus1`) vanno al nostro `skyunoplus1`."""
    channels = {
        row["id"]: row
        for row in csv.DictReader(io.StringIO(channels_csv))
        if row.get("country") == "IT" and row.get("id")
    }

    # Prima il nome principale, poi i nomi alternativi; un nome che porta a più
    # canali si scarta, per non attaccare la guida al canale sbagliato.
    def index(names_of) -> dict[str, set[str]]:
        found: dict[str, set[str]] = defaultdict(set)
        for cid, row in channels.items():
            for name in names_of(row):
                slug = external_slug(name)
                if slug:
                    found[slug].add(cid)
        return found

    primary = index(lambda row: [row["name"]])
    alternative = index(lambda row: [n for n in (row.get("alt_names") or "").split(";") if n.strip()])

    def resolve(slug: str) -> str | None:
        for table in (primary, alternative):
            ids = table.get(slug)
            if ids:
                if len(ids) == 1:
                    return next(iter(ids))
                # Più canali con lo stesso nome: si tiene quello ancora attivo, se è uno solo.
                active = [i for i in ids if not channels[i].get("closed")]
                return active[0] if len(active) == 1 else None
        return None

    feeds: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in csv.DictReader(io.StringIO(feeds_csv)):
        if row.get("channel") in channels and _FEED_NAME.fullmatch((row.get("name") or "").strip()):
            feeds[row["channel"]].append((row["id"], row["name"].strip()))

    result: dict[str, list[str]] = {}
    slugs = set(primary) | set(alternative)
    for slug in slugs:
        cid = resolve(slug)
        if cid is None:
            continue
        ids = [cid] + [f"{cid}@{fid}" for fid, name in feeds[cid] if name.upper() in ("SD", "HD")]
        result.setdefault(slug, [])
        for i in ids:
            if i not in result[slug]:
                result[slug].append(i)
        # Varianti +1/+24 del canale, con il loro slug (es. skyunoplus1).
        for fid, name in feeds[cid]:
            if name.upper() in ("SD", "HD"):
                continue
            plus_slug = channel_slug(f"{slug} {name}")
            result.setdefault(plus_slug, [])
            if f"{cid}@{fid}" not in result[plus_slug]:
                result[plus_slug].append(f"{cid}@{fid}")
    return result


def parse_xmltv_ids(content: bytes) -> dict[str, list[str]]:
    """Id dei canali di un feed XMLTV per id SEA-TV, abbinati per nome.

    Si leggono solo i `<channel>`, che stanno in cima al file."""
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    result: dict[str, list[str]] = defaultdict(list)
    for _, element in ET.iterparse(io.BytesIO(content), events=("end",)):
        if element.tag == "programme":
            break
        if element.tag != "channel":
            continue
        xml_id = element.get("id") or ""
        names = [d.text for d in element.iter("display-name") if d.text and d.text.strip()]
        # Senza nomi utili, il nome si ricava dall'id: "La.5.it" -> "La 5".
        # Il numero del canale in coda si toglie: "DMAX.HD..170.it" -> "DMAX HD".
        names.append(re.sub(r"(\.\.+\d+)?\.[a-z]{2}$", "", xml_id).replace(".", " "))
        for slug in {external_slug(n) for n in names} - {""}:
            if xml_id not in result[slug]:
                result[slug].append(xml_id)
        element.clear()
    return dict(result)


async def fetch_iptv_org(client: httpx.AsyncClient) -> dict[str, list[str]]:
    channels = await client.get(IPTV_ORG_CHANNELS)
    channels.raise_for_status()
    feeds = await client.get(IPTV_ORG_FEEDS)
    feeds.raise_for_status()
    return parse_iptv_org(channels.text, feeds.text)


async def fetch_epgshare(client: httpx.AsyncClient, urls: tuple[str, ...] = EPGSHARE_URLS) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for url in urls:
        response = await client.get(url, timeout=120)
        response.raise_for_status()
        for slug, ids in parse_xmltv_ids(response.content).items():
            merged.setdefault(slug, [])
            merged[slug] += [i for i in ids if i not in merged[slug]]
    return merged


SCHEMES = {"iptvorg": fetch_iptv_org, "epgshare": fetch_epgshare}
