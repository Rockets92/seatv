"""Configurazione letta dalle variabili d'ambiente (prefisso SEATV_)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/seatv.sqlite3"
    # Fonti da interrogare, in ordine: "tivu", "xmltv".
    sources: tuple[str, ...] = ("tivu",)
    xmltv_url: str | None = None
    # Giorni di palinsesto da scaricare a partire da oggi.
    days_ahead: int = 2
    # Giorni di palinsesto passato da conservare nel database.
    retention_days: int = 7
    refresh_hours: float = 12.0
    scheduler_enabled: bool = True
    http_timeout: float = 20.0
    http_concurrency: int = 4

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        sources = tuple(
            s.strip().lower()
            for s in env.get("SEATV_SOURCES", "tivu").split(",")
            if s.strip()
        )
        return cls(
            db_path=env.get("SEATV_DB_PATH", cls.db_path),
            sources=sources,
            xmltv_url=env.get("SEATV_XMLTV_URL") or None,
            days_ahead=int(env.get("SEATV_DAYS_AHEAD", cls.days_ahead)),
            retention_days=int(env.get("SEATV_RETENTION_DAYS", cls.retention_days)),
            refresh_hours=float(env.get("SEATV_REFRESH_HOURS", cls.refresh_hours)),
            scheduler_enabled=_bool(env.get("SEATV_SCHEDULER"), cls.scheduler_enabled),
            http_timeout=float(env.get("SEATV_HTTP_TIMEOUT", cls.http_timeout)),
            http_concurrency=int(env.get("SEATV_HTTP_CONCURRENCY", cls.http_concurrency)),
        )
