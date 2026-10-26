import asyncio
from datetime import datetime, timedelta, timezone

from seatv.align import align_hours, hour_offset
from seatv.config import ROME
from seatv.model import Guide, Programme
from seatv.sources import SourceChannel, SourceProgramme

# 26/10/2026, dopo il cambio dell'ora: a Roma UTC+1.
DAY = datetime(2026, 10, 26, 6, 0, tzinfo=ROME)
SCHEDULE = [(0, "Prima Pagina Tg5"), (120, "Tg5 Mattina"), (165, "Mattino Cinque"), (330, "Forum"), (420, "Tg5"), (460, "Beautiful")]


def rows(cid, shift_hours=0, source="tivu"):
    out = []
    for i, (minutes, title) in enumerate(SCHEDULE):
        start = DAY + timedelta(minutes=minutes, hours=shift_hours)
        stop = DAY + timedelta(minutes=SCHEDULE[i + 1][0] if i + 1 < len(SCHEDULE) else 500, hours=shift_hours)
        out.append(Programme(cid, start, stop, title, source=source))
    return out


def test_hour_offset_whole_hours_only():
    assert hour_offset(rows("canale5", 1), rows("canale5")) == 1
    assert hour_offset(rows("canale5"), rows("canale5")) == 0
    # Scarti di mezz'ora o pochi titoli in comune: non si tocca niente.
    assert hour_offset(rows("canale5", 0.5), rows("canale5")) == 0
    assert hour_offset(rows("canale5", 1)[:2], rows("canale5")[:2]) == 0


class FakeSky:
    name = "sky"

    async def fetch_channels(self, client):
        return [SourceChannel("c5", "Canale 5 HD"), SourceChannel("r1", "Rai 1 HD")]

    async def fetch_programmes(self, client, channels, days):
        out = []
        for channel in channels:
            for p in rows(channel.channel_id):
                out.append(SourceProgramme(channel.source_id, p.start.astimezone(timezone.utc), p.stop.astimezone(timezone.utc), p.title.upper()))
        return out


def test_align_hours_moves_only_shifted_channels():
    guide = Guide(generated_at=DAY)
    for cid, name, shift in (("canale5", "Canale 5", 1), ("rai1", "Rai 1", 0)):
        guide.add_channel(cid, name, "tivu", {}, [], [])
        guide.set_programmes(cid, rows(cid, shift))
    fixed = asyncio.run(align_hours(guide, "tivu", FakeSky(), None, [DAY.date()]))
    assert fixed == {"canale5": 1}
    assert [p.start.astimezone(ROME).strftime("%H:%M") for p in guide.programmes["canale5"]][:2] == ["06:00", "08:00"]
    assert guide.programmes["canale5"][0].title == "Prima Pagina Tg5"
    assert guide.programmes["rai1"] == rows("rai1")
