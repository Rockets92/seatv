"""Canali +1 e +24: lo stesso palinsesto del canale base, un'ora o un giorno dopo.

Le fonti non danno il palinsesto di questi canali (o non li elencano proprio),
quindi si ricavano dal canale base spostando ogni programma in avanti: su
"Rai 1 +1" il Tg1 delle 20:00 va in onda alle 21:00. Se una fonte dà il
palinsesto vero di un canale +1, si tiene quello.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import timedelta, timezone

from seatv.model import Guide
from seatv.sources import channel_slug

log = logging.getLogger(__name__)

# Canali base per ritardo in ore. I nomi si confrontano come id (`channel_slug`):
# "Sky Sport MotoGP" e "Sky Sport Motogp" sono lo stesso canale.
TIMESHIFTS: dict[int, tuple[str, ...]] = {
    1: (
        "Sky Uno", "Sky Arte", "Sky Atlantic", "Sky Serie", "Sky Nature", "Sky Investigation",
        "Comedy Central", "Sky Documentaries", "Sky Sport 24", "Sky Sport Uno", "Sky Sport Arena",
        "Sky Sport F1", "Sky Sport Golf", "Sky Sport Max", "Sky Sport MotoGP", "Sky Sport NBA",
        "Sky Sport Tennis", "Rai 1", "Rai 2", "Rai 3", "Rete 4", "Canale 5", "Italia 1", "La7",
        "Nove", "20 Mediaset", "Cielo", "Cine 34", "Giallo", "TV8", "27 Twentyseven", "DMAX",
        "Food Network", "Rai Premium", "Rai 4", "Rai Movie", "Boomerang", "Cartoon Network",
        "DeA Kids", "Nick Jr", "Nickelodeon", "Sky History", "Sky Crime", "Real Time",
        "Sky Cinema Action", "Sky Cinema Collection", "Sky Cinema Family",
    ),
    24: ("Sky Cinema Uno",),
}

# Altri id con cui le fonti possono chiamare lo stesso canale base.
ALTERNATIVES = {
    "skyhistory": ("history",),
    "skysportuno": ("skysport1",),
    "nickjr": ("nickjunior",),
}

_SHIFTED = re.compile(r"(?P<base>.+)plus(?P<hours>1|24)")


def _find_base(guide: Guide, name: str):
    slug = channel_slug(name)
    for candidate in (slug, *ALTERNATIVES.get(slug, ())):
        if candidate in guide.channels:
            return guide.channels[candidate]
    return None


def add_timeshifts(guide: Guide, previous: Guide | None = None) -> list[str]:
    """Aggiunge i canali +1/+24 e restituisce i nomi dei canali base non trovati
    o senza programmi.

    Va chiamata prima di togliere i programmi già finiti: il +24 di oggi è il
    palinsesto di ieri del canale base. Di ieri servono anche i programmi della
    guida precedente (`previous`), se la fonte oggi non li dà più."""
    # Canali +1/+24 che una fonte elenca già: si collegano al loro canale base.
    for channel in guide.channels.values():
        m = _SHIFTED.fullmatch(channel.id)
        if m and m["base"] in guide.channels:
            channel.timeshift = {"of": m["base"], "hours": int(m["hours"])}

    missing = []
    added = 0
    for hours, names in TIMESHIFTS.items():
        for name in names:
            base = _find_base(guide, name)
            if base is None:
                missing.append(name)
                continue
            cid = f"{base.id}plus{hours}"
            # In UTC: la notte del cambio dell'ora un'ora dopo resta un'ora dopo.
            delta = timedelta(hours=hours)
            shifted = []
            if cid not in guide.programmes:  # altrimenti la fonte dà il palinsesto vero
                rows = guide.programmes.get(base.id, [])
                old = previous.programmes.get(base.id, []) if previous is not None else []
                if rows:
                    old = [p for p in old if p.start < rows[0].start]
                shifted = [replace(p, channel_id=cid, start=p.start.astimezone(timezone.utc) + delta, stop=p.stop.astimezone(timezone.utc) + delta) for p in old + rows]
                if not shifted:
                    missing.append(name)
                    continue
            channel = guide.add_channel(
                cid,
                f"{base.name} +{hours}",
                base.sources[0],
                {},
                base.logo_urls,
                [f"{alias} +{hours}" for alias in base.aliases],
            )
            for source in base.sources:
                if source not in channel.sources:
                    channel.sources.append(source)
            channel.sources.sort()
            channel.timeshift = {"of": base.id, "hours": hours}
            if shifted:
                guide.set_programmes(cid, shifted)
                added += 1
    log.info("canali +1/+24: %d ricavati dal canale base", added)
    if missing:
        log.warning("canali +1/+24 senza canale base o senza programmi: %s", ", ".join(missing))
    return missing
