from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from seatv.config import Settings
from seatv.db import Database
from seatv.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"
# 07:00 ora italiana del 12 ottobre 2026.
NOW = datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def tivu_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/epg/channels.json":
        return httpx.Response(200, json=load("tivu_channels.json"))
    if path == "/api/epg/channels/42/date/2026-10-12":
        return httpx.Response(200, json=load("tivu_rai1_2026-10-12.json"))
    if path.startswith("/api/epg/channels/145/"):
        return httpx.Response(500)
    return httpx.Response(200, json={"events": []})


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(db_path=str(tmp_path / "test.sqlite3"), scheduler_enabled=False, days_ahead=2)


@pytest.fixture
def db(settings) -> Database:
    return Database(settings.db_path)


@pytest.fixture
def tivu_client():
    return httpx.AsyncClient(transport=httpx.MockTransport(tivu_handler))


@pytest.fixture
def api(settings):
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def anyio_backend():
    return "asyncio"
