"""Aggiornamento completo: scarica la guida e genera il sito statico.

Uso: `python -m seatv.build` (impostazioni nelle variabili SEATV_*, vedi README).
Il risultato in `dist/` si pubblica così com'è su Cloudflare Pages.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from seatv.collect import collect, guide_days
from seatv.config import Settings, http_client
from seatv.external_ids import SCHEMES
from seatv.export.site import copy_logos, write_site
from seatv.logos import LogoCache
from seatv.model import Guide

log = logging.getLogger(__name__)

SNAPSHOT = "guide.json.gz"
EXTERNAL_IDS = "external-ids.json"


def load_snapshot(cache_dir: Path) -> Guide | None:
    path = cache_dir / SNAPSHOT
    if not path.exists():
        return None
    try:
        return Guide.from_json(json.loads(gzip.decompress(path.read_bytes())))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("guida precedente illeggibile (%s): si riparte da zero", exc)
        return None


def save_snapshot(guide: Guide, cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    data = json.dumps(guide.to_json(), ensure_ascii=False, separators=(",", ":")).encode()
    (cache_dir / SNAPSHOT).write_bytes(gzip.compress(data, mtime=0))


async def load_external_ids(settings: Settings, client: httpx.AsyncClient, cache_dir: Path) -> dict[str, dict[str, list[str]]]:
    """Id delle liste IPTV per schema. Se una lista non si scarica, si usa
    l'ultima copia salvata, così i feed compatibili non perdono canali."""
    path = cache_dir / EXTERNAL_IDS
    try:
        cached = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        cached = {}
    result = {}
    for scheme in settings.external_ids:
        try:
            result[scheme] = await SCHEMES[scheme](client)
        except (httpx.HTTPError, ValueError, SyntaxError) as exc:  # SyntaxError: XML rotto
            log.warning("id della lista %s non scaricati (%s): si usa l'ultima copia", scheme, exc)
            result[scheme] = cached.get(scheme, {})
    if result:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**cached, **result}))
    return result


def assign_external_ids(guide: Guide, external: dict[str, dict[str, list[str]]]) -> None:
    for scheme, by_slug in external.items():
        for channel in guide.channels.values():
            ids = by_slug.get(channel.id)
            if ids:
                channel.external[scheme] = ids


async def download_logos(guide: Guide, cache: LogoCache, concurrency: int = 8) -> dict[str, Path]:
    """Scarica (o prende dalla cache) un logo per canale."""
    semaphore = asyncio.Semaphore(concurrency)

    async def one(channel_id: str, urls: list[str]) -> tuple[str, Path | None]:
        async with semaphore:
            found = await cache.get(channel_id, urls) if urls else None
            return channel_id, found[0] if found else None

    results = await asyncio.gather(*(one(c.id, c.logo_urls) for c in guide.channels.values()))
    return {channel_id: path for channel_id, path in results if path}


async def build(
    settings: Settings,
    client: httpx.AsyncClient | None = None,
    sources=None,
    now: datetime | None = None,
) -> dict:
    """Esegue tutto e restituisce lo stato (`api/health.json`)."""
    settings.validate()
    now = now or datetime.now(timezone.utc)
    cache_dir = Path(settings.cache_dir)

    owns_client = client is None
    client = client or http_client(settings)
    try:
        guide = await collect(settings, client=client, sources=sources, now=now, previous=load_snapshot(cache_dir))
        if not guide.programmes:
            raise RuntimeError("nessun programma scaricato da nessuna fonte: il sito pubblicato resta quello di prima")
        logos = await download_logos(guide, LogoCache(cache_dir / "logos", client))
        assign_external_ids(guide, await load_external_ids(settings, client, cache_dir))
    finally:
        if owns_client:
            await client.aclose()

    for channel in guide.channels.values():
        path = logos.get(channel.id)
        channel.logo = f"logos/{channel.id}{path.suffix}" if path else (channel.logo_urls[0] if channel.logo_urls else None)

    health = write_site(guide, settings, guide_days(now, settings.days_ahead))
    site = Path(settings.out_dir) / settings.feed_token if settings.feed_token else Path(settings.out_dir)
    copy_logos(logos, site)
    save_snapshot(guide, cache_dir)
    log.info(
        "sito generato in %s: %d canali, %d programmi, %d loghi",
        site, health["channels"], health["programmes"], len(logos),
    )
    return health


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scarica la guida TV e genera il sito statico SEA-TV.")
    parser.add_argument("--out", help="cartella del sito (default dist, o SEATV_OUT_DIR)")
    parser.add_argument("--strict", action="store_true", help="esce con errore se una fonte è fallita")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    if args.out:
        from dataclasses import replace

        settings = replace(settings, out_dir=args.out)
    try:
        health = asyncio.run(build(settings))
    except (RuntimeError, ValueError) as exc:
        log.error("%s", exc)
        raise SystemExit(1) from None
    if args.strict and health["status"] != "ok":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
