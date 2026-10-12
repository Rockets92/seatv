from datetime import datetime, timezone

from conftest import FIXTURES, load

from seatv.sources import channel_slug
from seatv.sources.tivu import parse_channels, parse_events
from seatv.sources.xmltv import parse_xmltv, parse_xmltv_time


def test_channel_slug_drops_hd_and_accents():
    assert channel_slug("Rai 1 HD") == "rai-1"
    assert channel_slug("Real time HD") == "real-time"
    assert channel_slug("Rai 4K") == "rai-4k"
    assert channel_slug("Tivù Sport") == "tivu-sport"


def test_tivu_channels_numbers():
    channels = {c.source_id: c for c in parse_channels(load("tivu_channels.json"))}
    assert channels["42"].numbers == {"dtt": 1, "sat": 1}
    assert channels["1"].numbers == {"sat": 101}
    assert channels["149"].numbers == {"dtt": 7}
    assert channels["42"].logo == "https://services.tivulaguida.it/uploads/channel/rai1hd.png"


def test_tivu_events_are_rome_time():
    programmes = parse_events(load("tivu_rai1_2026-10-12.json"), "42")
    # L'evento senza "program" viene scartato.
    assert len(programmes) == 5
    tg1 = programmes[1]
    assert tg1.title == "Tg1"
    assert tg1.start.astimezone(timezone.utc) == datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
    assert tg1.category == "Informazione"
    assert programmes[2].description is None


def test_xmltv_time():
    assert parse_xmltv_time("20261012180000 +0200") == datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)
    # Senza offset: ora italiana (CEST a ottobre).
    assert parse_xmltv_time("20261012200000") == datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)


def test_xmltv_parse():
    channels, programmes = parse_xmltv((FIXTURES / "sample.xmltv.xml").read_bytes())
    assert [(c.source_id, c.name, c.numbers) for c in channels] == [
        ("Rai1.it", "Rai 1", {"dtt": 1}),
        ("Nove.it", "NOVE", {"dtt": 9}),
    ]
    assert channels[0].logo == "https://example.org/rai1.png"
    assert len(programmes) == 4
    assert programmes[0].description.startswith("Viaggio")
