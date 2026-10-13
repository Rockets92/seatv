"""Cache su disco dei loghi dei canali.

La pagina web chiede i loghi a SEA-TV (`/channels/{id}/logo`) e non
direttamente a Tivù o a Sky: così vengono scaricati una volta sola, funzionano
anche se il sito di origine blocca i link esterni e restano disponibili se la
fonte è momentaneamente irraggiungibile.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

MAX_BYTES = 1_000_000
# Un indirizzo che non ha funzionato si riprova dopo un'ora.
RETRY_AFTER = 3600
# Alcuni siti (es. guidatv.sky.it) rifiutano i client che non sembrano un browser.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/png,image/*;q=0.8,*/*;q=0.5",
}
# Wikimedia invece rifiuta i finti browser e chiede un nome con un recapito.
WIKIMEDIA_HEADERS = {"User-Agent": "seatv/0.1 (+https://github.com/Rockets92/seatv)", "Accept": HEADERS["Accept"]}


def _headers(url: str) -> dict[str, str]:
    host = httpx.URL(url).host
    return WIKIMEDIA_HEADERS if host == "wikimedia.org" or host.endswith(".wikimedia.org") else HEADERS
# Solo immagini raster: un SVG servito dal nostro dominio potrebbe contenere script.
SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": ("png", "image/png"),
    b"\xff\xd8\xff": ("jpg", "image/jpeg"),
    b"GIF87a": ("gif", "image/gif"),
    b"GIF89a": ("gif", "image/gif"),
}
MEDIA_TYPES = {ext: media for ext, media in SIGNATURES.values()} | {"webp": "image/webp"}


def sniff(content: bytes) -> str | None:
    """Estensione del formato immagine, riconosciuto dai primi byte."""
    for signature, (ext, _) in SIGNATURES.items():
        if content.startswith(signature):
            return ext
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    return None


class LogoCache:
    def __init__(self, directory: Path, client: httpx.AsyncClient) -> None:
        self.directory = directory
        self.client = client
        self._failed: dict[str, float] = {}
        # Indirizzi a cui la fonte ha risposto che il file non esiste.
        self._missing: set[str] = set()

    def _stem(self, channel_id: str, url: str) -> str:
        # L'hash dell'indirizzo fa riscaricare il logo quando la fonte lo cambia.
        return f"{channel_id}-{hashlib.sha1(url.encode()).hexdigest()[:12]}"

    def _cached(self, channel_id: str, url: str) -> tuple[Path, str] | None:
        for path in self.directory.glob(f"{self._stem(channel_id, url)}.*"):
            return path, MEDIA_TYPES[path.suffix[1:]]
        return None

    async def get(self, channel_id: str, urls: list[str]) -> tuple[Path, str] | None:
        """Percorso del logo in cache e tipo MIME, provando gli indirizzi in ordine."""
        for url in urls:
            if cached := self._cached(channel_id, url):
                return cached
        for url in urls:
            if time.monotonic() - self._failed.get(url, -RETRY_AFTER) < RETRY_AFTER:
                continue
            if fetched := await self._download(channel_id, url):
                return fetched
            self._failed[url] = time.monotonic()
        return None

    def redirect_target(self, urls: list[str]) -> str | None:
        """Primo indirizzo che il browser può ancora provare: non quelli inesistenti."""
        return next((url for url in urls if url not in self._missing), None)

    async def _download(self, channel_id: str, url: str) -> tuple[Path, str] | None:
        try:
            response = await self.client.get(url, headers=_headers(url))
            response.raise_for_status()
            content = response.content
        except httpx.HTTPError as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (404, 410):
                self._missing.add(url)
            log.warning("logo di %s non scaricato da %s: %s", channel_id, url, exc)
            return None
        ext = sniff(content) if len(content) <= MAX_BYTES else None
        if ext is None:
            log.warning("logo di %s ignorato: non è un'immagine supportata (%s)", channel_id, url)
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        for old in self.directory.glob(f"{channel_id}-*.*"):
            old.unlink(missing_ok=True)
        path = self.directory / f"{self._stem(channel_id, url)}.{ext}"
        path.write_bytes(content)
        return path, MEDIA_TYPES[ext]
