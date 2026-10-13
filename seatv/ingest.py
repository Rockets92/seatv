"""Scarica canali e palinsesti dalle fonti configurate e li salva nel database.

Uso da riga di comando: `python -m seatv.ingest`
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx

from seatv.config import ROME, Settings
from seatv.db import Database
from seatv import logo_index
from seatv.lcn import DTT_FALLBACK
from seatv.sources import Source, SourceChannel, clean_name
from seatv.sources.sky import SkySource
from seatv.sources.tivu import TivuSource
from seatv.sources.xmltv import XmltvSource

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    source: str
    channels: int = 0
    programmes: int = 0
    error: str | None = None


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


def _representative(group: list[SourceChannel]) -> SourceChannel:
    """Tra le varianti dello stesso canale (es. SD e HD) sceglie quella numerata."""
    return max(group, key=lambda c: (len(c.numbers), -min(c.numbers.values(), default=0)))


def _merged_numbers(group: list[SourceChannel]) -> dict[str, int]:
    numbers: dict[str, int] = {}
    for channel in group:
        for platform, lcn in channel.numbers.items():
            numbers[platform] = min(lcn, numbers.get(platform, lcn))
    return numbers


async def ingest_source(
    db: Database,
    source: Source,
    client: httpx.AsyncClient,
    days: list[date],
    now: datetime,
    covered: set[str] | None = None,
) -> IngestResult:
    """Salva canali e programmi di una fonte.

    `covered` contiene i canali di cui una fonte precedente ha già fornito il
    palinsesto in questo giro: per quelli si aggiornano solo numeri e logo.
    """
    covered = covered if covered is not None else set()
    result = IngestResult(source=source.name)
    channels = await source.fetch_channels(client)

    groups: dict[str, list[SourceChannel]] = defaultdict(list)
    for channel in channels:
        if channel.channel_id:
            groups[channel.channel_id].append(channel)

    representatives = {cid: _representative(group) for cid, group in groups.items()}
    with db.connect() as conn:
        for cid, group in groups.items():
            rep = representatives[cid]
            # Il logo della variante scelta per primo, poi quelli delle altre (SD, HD...).
            logos = list(dict.fromkeys(url for c in [rep, *group] for url in c.logos))
            db.upsert_channel(
                conn, cid, clean_name(rep.name), logos[0] if logos else None, _merged_numbers(group), now,
                alt_logos=logos[1:],
            )
            for channel in group:
                db.link_source(conn, source.name, channel.source_id, cid)
    result.channels = len(groups)

    wanted = [rep for cid, rep in representatives.items() if cid not in covered]
    programmes = await source.fetch_programmes(client, wanted, days)
    by_source_id = {rep.source_id: cid for cid, rep in representatives.items()}
    per_channel: dict[str, list] = defaultdict(list)
    for p in programmes:
        cid = by_source_id.get(p.source_channel_id)
        if cid is None or p.stop <= p.start:
            continue
        per_channel[cid].append((p.start, p.stop, p.title, p.description, p.category, p.image))

    with db.connect() as conn:
        for cid, rows in per_channel.items():
            written = db.replace_programmes(conn, cid, source.name, rows)
            if written:
                covered.add(cid)
            result.programmes += written
    return result


async def run_ingest(
    settings: Settings,
    db: Database,
    client: httpx.AsyncClient | None = None,
    sources: list[Source] | None = None,
    now: datetime | None = None,
) -> list[IngestResult]:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ROME).date()
    days = [today + timedelta(days=i) for i in range(settings.days_ahead)]
    sources = sources if sources is not None else build_sources(settings)

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=settings.http_timeout,
            headers={"User-Agent": "seatv/0.1 (+https://github.com/Rockets92/seatv)"},
            follow_redirects=True,
        )
    results = []
    covered: set[str] = set()
    try:
        for source in sources:
            run_id = db.start_run(source.name, now)
            try:
                result = await ingest_source(db, source, client, days, now, covered)
            except httpx.HTTPError as exc:
                # Rete o servizio non raggiungibile: basta una riga, senza traceback.
                try:
                    url = str(exc.request.url)
                except RuntimeError:  # errore senza richiesta associata
                    url = "?"
                log.error("ingestione %s fallita: %s (%s)", source.name, exc, url)
                result = IngestResult(source=source.name, error=f"{type(exc).__name__}: {exc}")
            except Exception as exc:  # una fonte rotta non deve fermare le altre
                log.exception("ingestione %s fallita", source.name)
                result = IngestResult(source=source.name, error=f"{type(exc).__name__}: {exc}")
            db.finish_run(run_id, datetime.now(timezone.utc), result.channels, result.programmes, result.error)
            log.info("ingestione %s: %d canali, %d programmi", source.name, result.channels, result.programmes)
            results.append(result)
        if settings.logo_index_url:
            await add_fallback_logos(db, client, settings.logo_index_url)
    finally:
        if owns_client:
            await client.aclose()

    with db.connect() as conn:
        filled = db.fill_missing_numbers(conn, "dtt", DTT_FALLBACK)
        if filled:
            log.info("numeri DTT di riserva assegnati a %d canali", filled)
        db.prune_programmes(conn, now - timedelta(days=settings.retention_days))
    return results


async def add_fallback_logos(db: Database, client: httpx.AsyncClient, url: str) -> None:
    """Aggiunge i loghi di iptv-org come riserva; un canale +1 usa quello del canale base."""
    try:
        index = await logo_index.fetch(client, url)
    except httpx.HTTPError as exc:
        log.warning("loghi di riserva non scaricati da %s: %s", url, exc)
        return
    ids = [channel["id"] for channel in db.list_channels()]
    with db.connect() as conn:
        for cid in ids:
            urls = index.get(cid) or index.get(re.sub(r"plus(1|24)$", "", cid)) or []
            db.add_logos(conn, cid, urls)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    results = asyncio.run(run_ingest(settings, Database(settings.db_path)))
    if any(r.error for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
