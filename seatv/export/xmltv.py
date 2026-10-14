"""Feed XMLTV, il formato EPG che leggono i programmi IPTV (TiviMate, Kodi,
IPTV Smarters, Jellyfin, Plex...).

L'id di ogni canale (`rai1`, `skyunoplus1`) è quello da mettere come
`tvg-id` nella playlist M3U. Per i programmi che abbinano per nome, ogni
canale elenca anche i nomi usati dalle fonti (es. "Rai 1 HD").
"""

from __future__ import annotations

import gzip
from datetime import datetime
from typing import Callable, Iterator
from xml.sax.saxutils import escape, quoteattr

from seatv.config import ROME
from seatv.model import Channel, Guide

GENERATOR = "SEA-TV"
GENERATOR_URL = "https://github.com/Rockets92/seatv"


def xmltv_time(value: datetime) -> str:
    """Ora italiana con offset, es. "20261013210000 +0200"."""
    return value.astimezone(ROME).strftime("%Y%m%d%H%M%S %z")


def _clean(text: str) -> str:
    # Caratteri di controllo non ammessi in XML 1.0 (alcune descrizioni li contengono).
    return "".join(ch for ch in text if ch in "\t\n\r" or ord(ch) >= 0x20)


def _element(tag: str, text: str, lang: str | None = "it") -> str:
    attrs = f" lang={quoteattr(lang)}" if lang else ""
    return f"<{tag}{attrs}>{escape(_clean(text))}</{tag}>"


def iter_xmltv(
    guide: Guide,
    logo_url: Callable[[str | None], str | None],
    ids: Callable[[Channel], list[str]] = lambda channel: [channel.id],
) -> Iterator[str]:
    """Il documento a pezzi, per non tenerlo tutto in memoria.

    `logo_url` trasforma il logo del canale in un indirizzo assoluto; `ids`
    dà gli id con cui pubblicare ogni canale (per i feed compatibili con le
    liste IPTV, anche più di uno: il palinsesto si ripete per ciascuno)."""
    yield '<?xml version="1.0" encoding="UTF-8"?>\n'
    yield '<!DOCTYPE tv SYSTEM "xmltv.dtd">\n'
    yield (
        f"<tv generator-info-name={quoteattr(GENERATOR)} generator-info-url={quoteattr(GENERATOR_URL)}"
        f" date={quoteattr(guide.generated_at.astimezone(ROME).strftime('%Y%m%d%H%M%S %z'))}>\n"
    )
    channels = [(channel, ids(channel)) for channel in guide.sorted_channels()]
    for channel, channel_ids in channels:
        icon = logo_url(channel.logo)
        for channel_id in channel_ids:
            yield f"  <channel id={quoteattr(channel_id)}>\n"
            for name in [channel.name, *channel.aliases]:
                yield f"    {_element('display-name', name)}\n"
            if icon:
                yield f"    <icon src={quoteattr(icon)}/>\n"
            yield "  </channel>\n"
    for channel, channel_ids in channels:
        for channel_id in channel_ids:
            yield from _programmes(guide, channel, channel_id)
    yield "</tv>\n"


def _programmes(guide: Guide, channel: Channel, channel_id: str) -> Iterator[str]:
    for p in guide.programmes.get(channel.id, []):
        yield (
            f"  <programme start={quoteattr(xmltv_time(p.start))} stop={quoteattr(xmltv_time(p.stop))}"
            f" channel={quoteattr(channel_id)}>\n"
        )
        yield f"    {_element('title', p.title)}\n"
        if p.description:
            yield f"    {_element('desc', p.description)}\n"
        # Sky scrive "Genere/Sottogenere": diventano due categorie.
        for category in (p.category or "").split("/"):
            if category.strip():
                yield f"    {_element('category', category.strip())}\n"
        if p.image:
            yield f"    <icon src={quoteattr(p.image)}/>\n"
        yield "  </programme>\n"


def render_xmltv(
    guide: Guide,
    logo_url: Callable[[str | None], str | None] = lambda logo: logo,
    ids: Callable[[Channel], list[str]] = lambda channel: [channel.id],
) -> bytes:
    return "".join(iter_xmltv(guide, logo_url, ids)).encode("utf-8")


def gzip_bytes(content: bytes) -> bytes:
    # mtime fisso: lo stesso contenuto dà sempre lo stesso file.
    return gzip.compress(content, compresslevel=9, mtime=0)
