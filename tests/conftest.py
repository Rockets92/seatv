from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from seatv.config import Settings

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


def sky_handler(requests: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/gtv/v1/channels":
            return httpx.Response(200, json=load("sky_channels.json"))
        params = request.url.params
        if params.get("channels") == "9001" and params.get("from") == "2026-10-11T22:00:00Z":
            return httpx.Response(200, json=load("sky_tg24_2026-10-12.json"))
        return httpx.Response(200, json={"events": []})

    return handler


def combined_handler(requests: list[httpx.Request]):
    sky = sky_handler(requests)
    return lambda request: sky(request) if request.url.host == "apid.sky.it" else tivu_handler(request)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        days_ahead=2,
        logo_index_url="",
        out_dir=str(tmp_path / "dist"),
        cache_dir=str(tmp_path / "cache"),
        external_ids=(),
    )


@pytest.fixture
def tivu_client():
    return httpx.AsyncClient(transport=httpx.MockTransport(tivu_handler))


@pytest.fixture
def anyio_backend():
    return "asyncio"
