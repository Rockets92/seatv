"""Chiave API, ora dell'aggiornamento quotidiano e avvio sotto Passenger."""

import asyncio
import os
import runpy
from dataclasses import replace
from datetime import datetime, time
from pathlib import Path
from wsgiref.util import setup_testing_defaults

from conftest import NOW
from fastapi.testclient import TestClient

from seatv.config import ROME, Settings
from seatv.ingest import run_ingest
from seatv.main import _seconds_to_next_refresh, create_app
from seatv.sources.tivu import TivuSource


def test_api_key_required(settings):
    with TestClient(create_app(replace(settings, api_keys=("segreta", "altra")))) as client:
        assert client.get("/guide").status_code == 401
        assert client.get("/now", headers={"X-API-Key": "sbagliata"}).status_code == 401
        assert client.get("/now", headers={"X-API-Key": "segreta"}).status_code == 200
        assert client.get("/health", params={"api_key": "altra"}).status_code == 200
        # Pagina web e documentazione restano aperte: chiedono la chiave per leggere i dati.
        assert client.get("/").status_code == 200
        assert client.get("/docs").status_code == 200
        schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
        assert {s["name"] for s in schemes.values()} == {"X-API-Key", "api_key"}


def test_api_open_without_keys(api):
    assert api.get("/guide").status_code == 200
    assert "securitySchemes" not in api.get("/openapi.json").json().get("components", {})


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("SEATV_API_KEYS", " a, b ,")
    monkeypatch.setenv("SEATV_REFRESH_AT", "05:00")
    settings = Settings.from_env()
    assert settings.api_keys == ("a", "b")
    assert settings.refresh_at == time(5, 0)
    assert settings.days_ahead == 7


def test_next_refresh_at_fixed_time():
    settings = Settings(refresh_at=time(5, 0))
    before = datetime(2026, 10, 13, 4, 30, tzinfo=ROME)
    after = datetime(2026, 10, 13, 5, 0, tzinfo=ROME)
    assert _seconds_to_next_refresh(settings, before) == 30 * 60
    assert _seconds_to_next_refresh(settings, after) == 24 * 3600
    # Il 25 ottobre torna l'ora solare: dalle 05:00 alle 05:00 passano 25 ore.
    assert _seconds_to_next_refresh(settings, datetime(2026, 10, 24, 5, 0, tzinfo=ROME)) == 25 * 3600
    assert _seconds_to_next_refresh(Settings(refresh_hours=12), before) == 12 * 3600


def test_passenger_entry_point(settings, tivu_client, tmp_path, monkeypatch):
    asyncio.run(run_ingest(settings, create_app(settings).state.db, client=tivu_client, sources=[TivuSource()], now=NOW))
    root = Path(__file__).parent.parent
    monkeypatch.setenv("SEATV_DB_PATH", settings.db_path)
    monkeypatch.setenv("SEATV_API_KEYS", "segreta")
    monkeypatch.chdir(tmp_path)
    try:
        application = runpy.run_path(str(root / "passenger_wsgi.py"))["application"]
    finally:
        os.chdir(tmp_path)

    def call(path, query="", key=None):
        environ = {"PATH_INFO": path, "QUERY_STRING": query}
        if key:
            environ["HTTP_X_API_KEY"] = key
        setup_testing_defaults(environ)
        statuses = []
        body = b"".join(application(environ, lambda status, headers, exc_info=None: statuses.append(status)))
        return statuses[0], body

    assert call("/channels/rai1")[0].startswith("401")
    status, body = call("/channels/rai1", key="segreta")
    assert status.startswith("200") and b"Rai 1" in body
