"""Corregge i canali di una fonte con gli orari spostati di ore intere.

Dal cambio dell'ora del 25/10/2026 Tivù dà gli orari di Mediaset, Discovery,
Sky (Cielo, TV8) e altri un'ora avanti: il Tg5 delle 08:00 risulta alle
09:00, mentre Rai e La7 sono giusti. Per ogni canale che anche Sky elenca si
confrontano i due palinsesti e, se gli stessi titoli sono quasi tutti
spostati della stessa quantità di ore intere, si spostano i programmi
della fonte.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta, timezone

import httpx

from seatv.model import Guide, Programme
from seatv.sources import Source

log = logging.getLogger(__name__)

# Uno scarto vince se ha almeno MIN_MATCHES titoli e il doppio di ogni altro.
MIN_MATCHES = 4
MAX_HOURS = 3
TOLERANCE = 6 * 60  # secondi: Sky a volte arrotonda (05:59 invece di 06:00)


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())[:12]


def hour_offset(ours: list[Programme], reference: list[Programme]) -> int:
    """Ore intere di cui `ours` è avanti rispetto a `reference` (0 se non si
    capisce con sicurezza). Per ogni scarto da -MAX_HOURS a +MAX_HOURS si
    contano i programmi che con quello scarto trovano lo stesso titolo."""
    by_title: dict[str, list] = {}
    for p in reference:
        by_title.setdefault(_key(p.title), []).append(p.start)
    hours: Counter[int] = Counter()
    for p in ours:
        starts = by_title.get(_key(p.title), [])
        for h in range(-MAX_HOURS, MAX_HOURS + 1):
            target = p.start - timedelta(hours=h)
            if any(abs((target - s).total_seconds()) <= TOLERANCE for s in starts):
                hours[h] += 1
    if not hours:
        return 0
    (best, count), *others = hours.most_common()
    if best == 0 or count < MIN_MATCHES:
        return 0
    return best if all(count >= 2 * c for _, c in others) else 0


async def align_hours(guide: Guide, target: str, reference: Source, client: httpx.AsyncClient, days: list[date]) -> dict[str, int]:
    """Sposta i programmi della fonte `target` nei canali in cui sono avanti
    di ore intere rispetto alla fonte `reference`. Restituisce le ore
    corrette per canale."""
    channels = {c.channel_id: c for c in await reference.fetch_channels(client) if c.channel_id}
    common = [
        channels[cid]
        for cid, rows in guide.programmes.items()
        if cid in channels and rows and rows[0].source == target
    ]
    if not common:
        return {}
    ids = {c.source_id: c.channel_id for c in common}
    reference_rows: dict[str, list[Programme]] = {}
    for p in await reference.fetch_programmes(client, common, days):
        cid = ids.get(p.source_channel_id)
        if cid is not None:
            reference_rows.setdefault(cid, []).append(Programme(cid, p.start, p.stop, p.title))

    fixed = {}
    for cid, ref in reference_rows.items():
        rows = guide.programmes[cid]
        first, last = min(p.start for p in ref), max(p.start for p in ref)
        window = [p for p in rows if first - timedelta(hours=MAX_HOURS) <= p.start <= last + timedelta(hours=MAX_HOURS)]
        hours = hour_offset(window, ref)
        if hours:
            delta = timedelta(hours=hours)
            guide.set_programmes(cid, [replace(p, start=p.start.astimezone(timezone.utc) - delta, stop=p.stop.astimezone(timezone.utc) - delta) for p in rows])
            fixed[cid] = hours
    if fixed:
        log.warning(
            "%s: orari spostati rispetto a %s, corretti in %d canali: %s",
            target,
            reference.name,
            len(fixed),
            ", ".join(f"{cid} {h:+d}h" for cid, h in sorted(fixed.items())),
        )
    return fixed
