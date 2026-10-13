"""Scarica canali e palinsesti dalle fonti configurate e li unisce in una `Guide`."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

import httpx

from seatv import logo_index
from seatv.config import ROME, Settings, http_client
from seatv.lcn import DTT_FALLBACK
from seatv.model import Guide, Programme, SourceRun
from seatv.sources import Source, SourceChannel, clean_name
from seatv.sources.sky import SkySource
from seatv.sources.tivu import TivuSource
from seatv.sources.xmltv import XmltvSource

log = logging.getLogger(__name__)


def build_sources(settings: Settings) -> list[Source]:
    sources: list[Source] = []
    for name in settings.sources:
        if name == "tivu":
            sources.append(TivuSource(concurrency=settings.http_concurrency, base_url=settings.tivu_url))
        elif name == "sky":
            sources.append(SkySource(concurrency=settings.http_concurrency))
        elif name == "xmltv":
            if not settings.xmltv_url:
                raise ValueError("la fonte xmltv richiede SEATV_XMLTV_URL")
            sources.append(XmltvSource(settings.xmltv_url))
        else:
            raise ValueError(f"fonte sconosciuta: {name}")
    return sources


def window_start(now: datetime) -> datetime:
    """Inizio della guida: la mezzanotte italiana di oggi."""
    return datetime.combine(now.astimezone(ROME).date(), time.min, tzinfo=ROME)


def guide_days(now: datetime, days_ahead: int) -> list[date]:
    today = now.astimezone(ROME).date()
    return [today + timedelta(days=i) for i in range(days_ahead)]


def _representative(group: list[SourceChannel]) -> SourceChannel:
    """Tra le varianti dello stesso canale (es. SD e HD) sceglie quella numerata."""
    return max(group, key=lambda c: (len(c.numbers), -min(c.numbers.values(), default=0)))


def _merged_numbers(group: list[SourceChannel]) -> dict[str, int]:
    numbers: dict[str, int] = {}
    for channel in group:
        for platform, lcn in channel.numbers.items():
            numbers[platform] = min(lcn, numbers.get(platform, lcn))
    return numbers


async def collect_source(guide: Guide, source: Source, client: httpx.AsyncClient, days: list[date], run: SourceRun) -> None:
    """Aggiunge alla guida canali e programmi di una fonte.

    I canali di cui una fonte precedente ha già dato il palinsesto prendono
    da questa solo numeri, loghi e nomi alternativi."""
    channels = await source.fetch_channels(client)

    groups: dict[str, list[SourceChannel]] = defaultdict(list)
    for channel in channels:
        if channel.channel_id:
            groups[channel.channel_id].append(channel)

    representatives = {cid: _representative(group) for cid, group in groups.items()}
    for cid, group in groups.items():
        rep = representatives[cid]
        # Il logo della variante scelta per primo, poi quelli delle altre (SD, HD...).
        logos = list(dict.fromkeys(url for c in [rep, *group] for url in c.logos))
        aliases = list(dict.fromkeys(c.name for c in group))
        guide.add_channel(cid, clean_name(rep.name), source.name, _merged_numbers(group), logos, aliases)
    run.channels = len(groups)

    wanted = [rep for cid, rep in representatives.items() if cid not in guide.programmes]
    programmes = await source.fetch_programmes(client, wanted, days)
    by_source_id = {rep.source_id: cid for cid, rep in representatives.items()}
    per_channel: dict[str, list[Programme]] = defaultdict(list)
    for p in programmes:
        cid = by_source_id.get(p.source_channel_id)
        if cid is None:
            continue
        per_channel[cid].append(
            Programme(cid, p.start, p.stop, p.title, p.description, p.category, p.image, source.name)
        )
    for cid, rows in per_channel.items():
        run.programmes += guide.set_programmes(cid, rows)


async def collect(
    settings: Settings,
    client: httpx.AsyncClient | None = None,
    sources: list[Source] | None = None,
    now: datetime | None = None,
    previous: Guide | None = None,
) -> Guide:
    """Costruisce la guida da tutte le fonti. `previous` è la guida
    dell'aggiornamento prima: se una fonte fallisce, i suoi canali tengono i
    programmi già noti che non sono ancora finiti."""
    now = now or datetime.now(timezone.utc)
    days = guide_days(now, settings.days_ahead)
    sources = sources if sources is not None else build_sources(settings)
    guide = Guide(generated_at=now)

    owns_client = client is None
    if client is None:
        client = http_client(settings)
    try:
        for source in sources:
            run = SourceRun(source=source.name, started_at=datetime.now(timezone.utc))
            try:
                await collect_source(guide, source, client, days, run)
            except httpx.HTTPError as exc:
                # Rete o servizio non raggiungibile: basta una riga, senza traceback.
                try:
                    url = str(exc.request.url)
                except RuntimeError:  # errore senza richiesta associata
                    url = "?"
                log.error("fonte %s fallita: %s (%s)", source.name, exc, url)
                run.error = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # una fonte rotta non deve fermare le altre
                log.exception("fonte %s fallita", source.name)
                run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(timezone.utc)
            log.info("fonte %s: %d canali, %d programmi", source.name, run.channels, run.programmes)
            guide.runs.append(run)
        if settings.logo_index_url:
            await add_fallback_logos(guide, client, settings.logo_index_url)
    finally:
        if owns_client:
            await client.aclose()

    start = window_start(now)
    failed = {run.source for run in guide.runs if run.error}
    if previous is not None and failed:
        reused = guide.reuse_from(previous, failed, start)
        for run in guide.runs:
            run.reused = reused.get(run.source, 0)
            if run.reused:
                log.warning("fonte %s: %d canali presi dalla guida precedente", run.source, run.reused)

    filled = guide.fill_missing_numbers("dtt", DTT_FALLBACK)
    if filled:
        log.info("numeri DTT di riserva assegnati a %d canali", filled)
    guide.prune(start)
    return guide


async def add_fallback_logos(guide: Guide, client: httpx.AsyncClient, url: str) -> None:
    """Aggiunge i loghi di iptv-org come riserva; un canale +1 usa quello del canale base."""
    try:
        index = await logo_index.fetch(client, url)
    except httpx.HTTPError as exc:
        log.warning("loghi di riserva non scaricati da %s: %s", url, exc)
        return
    for channel in guide.channels.values():
        urls = index.get(channel.id) or index.get(re.sub(r"plus(1|24)$", "", channel.id)) or []
        for logo in urls:
            if logo not in channel.logo_urls:
                channel.logo_urls.append(logo)
