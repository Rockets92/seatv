"""Configurazione letta dalle variabili d'ambiente (prefisso SEATV_)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")

# Il token entra nel percorso pubblico del sito: solo caratteri sicuri in un URL
# e abbastanza lungo da non essere indovinato.
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,128}")


@dataclass(frozen=True)
class Settings:
    # Fonti da interrogare: "tivu", "sky", "xmltv". Se due fonti coprono lo
    # stesso canale, vince la prima.
    sources: tuple[str, ...] = ("tivu", "sky")
    xmltv_url: str | None = None
    # Indirizzo dell'API Tivù, da cambiare se il servizio si sposta.
    tivu_url: str = "https://services.tivulaguida.it"
    # Elenco pubblico di loghi di riserva (iptv-org); vuoto = non usarlo.
    logo_index_url: str = "https://raw.githubusercontent.com/iptv-org/database/master/data/logos.csv"
    # Giorni di palinsesto da scaricare a partire da oggi (oggi compreso).
    days_ahead: int = 7
    # Cartella del sito generato, da pubblicare così com'è.
    out_dir: str = "dist"
    # Cartella che sopravvive tra un aggiornamento e l'altro: loghi già
    # scaricati e ultima guida, usata se una fonte non risponde.
    cache_dir: str = ".cache"
    # Parte segreta del percorso: il sito sta in /<token>/. Vuoto = nella radice.
    feed_token: str = ""
    # Indirizzo pubblico del sito (es. https://seatv.pages.dev), per i link
    # assoluti ai loghi nel feed XMLTV. Vuoto = loghi delle fonti originali.
    public_url: str = ""
    # Liste IPTV di cui pubblicare un feed con i loro id dei canali
    # ("iptvorg", "epgshare"); vuoto = solo il feed con gli id SEA-TV.
    external_ids: tuple[str, ...] = ("iptvorg", "epgshare")
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
            sources=sources,
            xmltv_url=env.get("SEATV_XMLTV_URL") or None,
            tivu_url=env.get("SEATV_TIVU_URL") or cls.tivu_url,
            logo_index_url=env.get("SEATV_LOGO_INDEX_URL", cls.logo_index_url),
            days_ahead=int(env.get("SEATV_DAYS_AHEAD") or cls.days_ahead),
            out_dir=env.get("SEATV_OUT_DIR") or cls.out_dir,
            cache_dir=env.get("SEATV_CACHE_DIR") or cls.cache_dir,
            feed_token=(env.get("SEATV_FEED_TOKEN") or "").strip(),
            public_url=(env.get("SEATV_PUBLIC_URL") or "").strip().rstrip("/"),
            external_ids=tuple(
                s.strip().lower()
                for s in env.get("SEATV_EXTERNAL_IDS", ",".join(cls.external_ids)).split(",")
                if s.strip()
            ),
            http_timeout=float(env.get("SEATV_HTTP_TIMEOUT") or cls.http_timeout),
            http_concurrency=int(env.get("SEATV_HTTP_CONCURRENCY") or cls.http_concurrency),
        )

    def validate(self) -> None:
        if self.feed_token and not TOKEN_PATTERN.fullmatch(self.feed_token):
            raise ValueError(
                "SEATV_FEED_TOKEN deve avere da 16 a 128 caratteri tra lettere, cifre, '-' e '_'"
            )
        if self.public_url and not self.public_url.startswith(("https://", "http://")):
            raise ValueError("SEATV_PUBLIC_URL deve iniziare con https://")
        from seatv.external_ids import SCHEMES

        unknown = set(self.external_ids) - set(SCHEMES)
        if unknown:
            raise ValueError(f"SEATV_EXTERNAL_IDS: schemi sconosciuti {sorted(unknown)}, ammessi {sorted(SCHEMES)}")
        if self.days_ahead < 1:
            raise ValueError("SEATV_DAYS_AHEAD deve essere almeno 1")

    @property
    def site_url(self) -> str:
        """Indirizzo assoluto della cartella del sito, se noto."""
        if not self.public_url:
            return ""
        return f"{self.public_url}/{self.feed_token}" if self.feed_token else self.public_url


def http_client(settings: Settings):
    """Client HTTP condiviso. Gli errori di connessione, compresi i nomi che
    il DNS a volte non risolve, si riprovano fino a 3 volte con attese crescenti."""
    import httpx

    return httpx.AsyncClient(
        timeout=settings.http_timeout,
        headers={"User-Agent": "seatv/0.2 (+https://github.com/Rockets92/seatv)"},
        follow_redirects=True,
        transport=httpx.AsyncHTTPTransport(retries=3),
    )
