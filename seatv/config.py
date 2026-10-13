"""Configurazione letta dalle variabili d'ambiente (prefisso SEATV_)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/seatv.sqlite3"
    # Cartella della cache dei loghi; vuota = "logos" accanto al database.
    logo_dir: str = ""
    # Fonti da interrogare: "tivu", "sky", "xmltv". Se due fonti coprono lo
    # stesso canale, vince la prima.
    sources: tuple[str, ...] = ("tivu", "sky")
    xmltv_url: str | None = None
    # Indirizzo dell'API Tivù, da cambiare se il servizio si sposta.
    tivu_url: str = "https://services.tivulaguida.it"
    # Elenco pubblico di loghi di riserva (iptv-org); vuoto = non usarlo.
    logo_index_url: str = "https://raw.githubusercontent.com/iptv-org/database/master/data/logos.csv"
    # Giorni di palinsesto da scaricare a partire da oggi (oggi compreso):
    # sono anche i giorni che la pagina web lascia scegliere.
    days_ahead: int = 7
    # Giorni di palinsesto passato da conservare nel database.
    retention_days: int = 7
    refresh_hours: float = 12.0
    # Ora italiana dell'aggiornamento quotidiano, es. 05:00; se impostata
    # sostituisce refresh_hours.
    refresh_at: time | None = None
    # Chiavi che danno accesso ai dati; vuoto = API aperta a tutti.
    api_keys: tuple[str, ...] = ()
    scheduler_enabled: bool = True
    http_timeout: float = 20.0
    http_concurrency: int = 4

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        sources = tuple(
            s.strip().lower()
            for s in env.get("SEATV_SOURCES", ",".join(cls.sources)).split(",")
            if s.strip()
        )
        return cls(
            db_path=env.get("SEATV_DB_PATH", cls.db_path),
            logo_dir=env.get("SEATV_LOGO_DIR", cls.logo_dir),
            sources=sources,
            xmltv_url=env.get("SEATV_XMLTV_URL") or None,
            tivu_url=env.get("SEATV_TIVU_URL") or cls.tivu_url,
            logo_index_url=env.get("SEATV_LOGO_INDEX_URL", cls.logo_index_url),
            days_ahead=int(env.get("SEATV_DAYS_AHEAD", cls.days_ahead)),
            retention_days=int(env.get("SEATV_RETENTION_DAYS", cls.retention_days)),
            refresh_hours=float(env.get("SEATV_REFRESH_HOURS", cls.refresh_hours)),
            refresh_at=time.fromisoformat(env["SEATV_REFRESH_AT"]) if env.get("SEATV_REFRESH_AT") else None,
            api_keys=tuple(k.strip() for k in env.get("SEATV_API_KEYS", "").split(",") if k.strip()),
            scheduler_enabled=_bool(env.get("SEATV_SCHEDULER"), cls.scheduler_enabled),
            http_timeout=float(env.get("SEATV_HTTP_TIMEOUT", cls.http_timeout)),
            http_concurrency=int(env.get("SEATV_HTTP_CONCURRENCY", cls.http_concurrency)),
        )


def http_client(settings: Settings):
    """Client HTTP condiviso. Gli errori di connessione, compresi i nomi che
    il DNS a volte non risolve, si riprovano fino a 3 volte con attese crescenti."""
    import httpx

    return httpx.AsyncClient(
        timeout=settings.http_timeout,
        headers={"User-Agent": "seatv/0.1 (+https://github.com/Rockets92/seatv)"},
        follow_redirects=True,
        transport=httpx.AsyncHTTPTransport(retries=3),
    )
