from datetime import datetime, timedelta, timezone

from seatv.model import Guide, Programme
from seatv.timeshift import add_timeshifts

T0 = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)  # 20:00 ora italiana


def programme(channel_id, start, title, hours=1):
    return Programme(channel_id, start, start + timedelta(hours=hours), title, source="sky")


def guide_with(channels, now=T0):
    guide = Guide(generated_at=now)
    for cid, name, rows in channels:
        guide.add_channel(cid, name, "sky", {"sky": 100 + len(guide.channels)}, [f"https://example.org/{cid}.png"], [f"{name} HD"])
        guide.set_programmes(cid, rows)
    return guide


def test_plus1_is_base_one_hour_later():
    guide = guide_with([("rai1", "Rai 1", [programme("rai1", T0, "Tg1"), programme("rai1", T0 + timedelta(hours=1), "Film")])])
    missing = add_timeshifts(guide)

    plus1 = guide.channels["rai1plus1"]
    assert plus1.name == "Rai 1 +1"
    assert plus1.numbers == {}
    assert plus1.aliases == ["Rai 1 HD +1"]
    assert plus1.logo_urls == ["https://example.org/rai1.png"]
    assert plus1.timeshift == {"of": "rai1", "hours": 1}
    assert [(p.start, p.title) for p in guide.programmes["rai1plus1"]] == [
        (T0 + timedelta(hours=1), "Tg1"),
        (T0 + timedelta(hours=2), "Film"),
    ]
    # I canali base che mancano sono segnalati, senza creare canali vuoti.
    assert "Canale 5" in missing
    assert "canale5plus1" not in guide.channels


def test_plus24_uses_yesterday_from_previous_guide():
    yesterday = T0 - timedelta(days=1)
    previous = guide_with([("skycinemauno", "Sky Cinema Uno", [programme("skycinemauno", yesterday, "Film di ieri"), programme("skycinemauno", T0, "Film di oggi")])])
    guide = guide_with([("skycinemauno", "Sky Cinema Uno", [programme("skycinemauno", T0, "Film di oggi")])])
    add_timeshifts(guide, previous)
    rows = guide.programmes["skycinemaunoplus24"]
    assert [(p.start, p.title) for p in rows] == [(T0, "Film di ieri"), (T0 + timedelta(days=1), "Film di oggi")]


def test_source_schedule_wins_and_is_linked_to_base():
    guide = guide_with([
        ("skyuno", "Sky Uno", [programme("skyuno", T0, "MasterChef")]),
        ("skyunoplus1", "Sky Uno +1", [programme("skyunoplus1", T0, "Replica")]),
        ("skycinemadueplus24", "Sky Cinema Due +24", [programme("skycinemadueplus24", T0, "Film")]),
        ("skycinemadue", "Sky Cinema Due", [programme("skycinemadue", T0, "Film")]),
    ])
    add_timeshifts(guide)
    assert [p.title for p in guide.programmes["skyunoplus1"]] == ["Replica"]
    assert guide.channels["skyunoplus1"].timeshift == {"of": "skyuno", "hours": 1}
    # Anche i +1/+24 delle fonti fuori elenco si collegano al canale base.
    assert guide.channels["skycinemadueplus24"].timeshift == {"of": "skycinemadue", "hours": 24}


def test_shifted_channels_follow_their_base_and_survive_snapshot():
    guide = guide_with([("rai1", "Rai 1", [programme("rai1", T0, "Tg1")]), ("rai2", "Rai 2", [programme("rai2", T0, "Tg2")])])
    add_timeshifts(guide)
    assert [c.id for c in guide.sorted_channels()][:4] == ["rai1", "rai1plus1", "rai2", "rai2plus1"]
    restored = Guide.from_json(guide.to_json())
    assert restored.channels["rai1plus1"].timeshift == {"of": "rai1", "hours": 1}
