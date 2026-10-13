"""Cache su disco dei loghi dei canali.

La pagina web chiede i loghi a SEA-TV (`/channels/{id}/logo`) e non
direttamente a Tivù o a Sky: così vengono scaricati una volta sola, funzionano
anche se il sito di origine blocca i link esterni e restano disponibili se la
fonte è momentaneamente irraggiungibile.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

MAX_BYTES = 1_000_000
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
        self._failed: set[str] = set()

    def _stem(self, channel_id: str, url: str) -> str:
        # L'hash dell'indirizzo fa riscaricare il logo quando la fonte lo cambia.
        return f"{channel_id}-{hashlib.sha1(url.encode()).hexdigest()[:12]}"

    async def get(self, channel_id: str, url: str) -> tuple[Path, str] | None:
        """Percorso del logo in cache e tipo MIME, scaricandolo se serve."""
        stem = self._stem(channel_id, url)
        for path in self.directory.glob(f"{stem}.*"):
            return path, MEDIA_TYPES[path.suffix[1:]]
        if url in self._failed:
            return None
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            content = response.content
        except httpx.HTTPError as exc:
            log.warning("logo di %s non scaricato da %s: %s", channel_id, url, exc)
            self._failed.add(url)
            return None
        ext = sniff(content) if len(content) <= MAX_BYTES else None
        if ext is None:
            log.warning("logo di %s ignorato: non è un'immagine supportata (%s)", channel_id, url)
            self._failed.add(url)
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        for old in self.directory.glob(f"{channel_id}-*.*"):
            old.unlink(missing_ok=True)
        path = self.directory / f"{stem}.{ext}"
        path.write_bytes(content)
        return path, MEDIA_TYPES[ext]
