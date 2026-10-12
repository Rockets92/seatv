import asyncio

import pytest

from conftest import NOW

from seatv.ingest import run_ingest
from seatv.sources.tivu import TivuSource


@pytest.fixture
def loaded(api, settings, tivu_client):
    asyncio.run(run_ingest(settings, api.app.state.db, client=tivu_client, sources=[TivuSource()], now=NOW))
    return api


def test_channels(loaded):
    response = loaded.get("/channels", params={"platform": "dtt"})
    assert response.status_code == 200
    assert [(c["id"], c["numbers"]["dtt"]) for c in response.json()] == [("rai-1", 1), ("canale-5", 5), ("la7", 7)]
    assert len(loaded.get("/channels").json()) == 4


def test_channel_unknown(loaded):
    assert loaded.get("/channels/nope").status_code == 404
    assert loaded.get("/channels/nope/schedule").status_code == 404


def test_bad_platform(loaded):
    assert loaded.get("/channels", params={"platform": "cable"}).status_code == 422


def test_schedule(loaded):
    response = loaded.get("/channels/rai-1/schedule", params={"date": "2026-10-12"})
    assert response.status_code == 200
    body = response.json()
    assert body["channel"]["name"] == "Rai 1"
    # Lo "Speciale notte" iniziato l'11 non appartiene al 12.
    assert [p["title"] for p in body["programmes"]] == ["Tg1", "Unomattina", "Tg1", "Film della sera"]
    assert body["programmes"][0]["start"] == "2026-10-12T06:00:00+02:00"
    assert loaded.get("/channels/rai-1/schedule", params={"date": "2026-10-20"}).json()["programmes"] == []


def test_now(loaded):
    response = loaded.get("/now", params={"platform": "dtt", "at": "2026-10-12T07:00:00+02:00"})
    assert response.status_code == 200
    entries = {e["channel"]["id"]: e for e in response.json()}
    assert entries["rai-1"]["now"]["title"] == "Unomattina"
    assert entries["rai-1"]["next"]["start"] == "2026-10-12T20:00:00+02:00"
    assert entries["la7"]["now"] is None


def test_channel_now_naive_time_is_rome(loaded):
    body = loaded.get("/channels/rai-1/now", params={"at": "2026-10-12T21:00:00"}).json()
    assert body["now"] is None
    assert body["next"]["title"] == "Film della sera"


def test_health(loaded):
    body = loaded.get("/health").json()
    assert body["status"] == "ok"
    assert body["sources"][0]["source"] == "tivu"
    assert body["sources"][0]["programmes"] == 5


def test_health_degraded_before_first_ingest(api):
    assert api.get("/health").json() == {"status": "degraded", "sources": []}
