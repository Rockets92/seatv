"""La guida TV in memoria: canali unificati tra le fonti e i loro programmi.

Ogni aggiornamento ricostruisce la guida da zero e la esporta in file
statici; non serve un database. Per non perdere dati quando una fonte non
risponde, la guida precedente si salva come istantanea (`to_json`) e si usa
per riempire i canali rimasti senza programmi.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

PLATFORMS = ("dtt", "tivusat", "sky")


@dataclass
class Channel:
    id: str
    # Nome da mostrare: quello della prima fonte che ha visto il canale.
    name: str
    # Numero del canale per piattaforma, es. {"dtt": 1, "tivusat": 1, "sky": 101}.
    numbers: dict[str, int] = field(default_factory=dict)
    # Fonti che elencano il canale, es. ["sky", "tivu"].
    sources: list[str] = field(default_factory=list)
    # Indirizzi dei loghi da provare, nell'ordine.
    logo_urls: list[str] = field(default_factory=list)
    # Nomi originali delle fonti ("Rai 1 HD"), utili ai programmi IPTV che
    # abbinano i canali per nome.
    aliases: list[str] = field(default_factory=list)
    # Logo pubblicato: percorso relativo nel sito (logos/rai1.png) o, se non
    # si è riusciti a scaricarlo, l'indirizzo originale.
    logo: str | None = None
    # Id dello stesso canale nelle liste IPTV diffuse, per schema:
    # {"iptvorg": ["Rai2.it", "Rai2.it@HD"], "epgshare": ["Rai.2.HD.it"]}.
    external: dict[str, list[str]] = field(default_factory=dict)

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "logo": self.logo,
            "numbers": self.numbers,
            "sources": self.sources,
            "ids": self.external,
        }


@dataclass(frozen=True)
class Programme:
    channel_id: str
    start: datetime  # timezone-aware
    stop: datetime  # timezone-aware
    title: str
    description: str | None = None
    category: str | None = None
    image: str | None = None
    # Fonte da cui arriva il programma.
    source: str = ""


@dataclass
class SourceRun:
    source: str
    started_at: datetime
    finished_at: datetime | None = None
    channels: int = 0
    programmes: int = 0
    error: str | None = None
    # Canali che, con la fonte giù, hanno ripreso i programmi della guida precedente.
    reused: int = 0


@dataclass
class Guide:
    generated_at: datetime
    channels: dict[str, Channel] = field(default_factory=dict)
    programmes: dict[str, list[Programme]] = field(default_factory=dict)
    runs: list[SourceRun] = field(default_factory=list)

    # --- scrittura -------------------------------------------------------

    def add_channel(
        self,
        channel_id: str,
        name: str,
        source: str,
        numbers: dict[str, int],
        logo_urls: list[str],
        aliases: list[str] = (),
    ) -> Channel:
        """Aggiunge il canale o unisce i dati di un'altra fonte a quello già noto."""
        channel = self.channels.get(channel_id)
        if channel is None:
            channel = self.channels[channel_id] = Channel(id=channel_id, name=name)
        for platform, lcn in numbers.items():
            if platform in PLATFORMS:
                channel.numbers[platform] = lcn
        if source not in channel.sources:
            channel.sources.append(source)
            channel.sources.sort()
        for url in logo_urls:
            if url and url not in channel.logo_urls:
                channel.logo_urls.append(url)
        for alias in aliases:
            if alias and alias != channel.name and alias not in channel.aliases:
                channel.aliases.append(alias)
        return channel

    def set_programmes(self, channel_id: str, programmes: list[Programme]) -> int:
        """Programmi del canale, ordinati e senza doppioni con lo stesso inizio."""
        unique = {p.start: p for p in programmes if p.stop > p.start}
        rows = sorted(unique.values(), key=lambda p: p.start)
        if rows:
            self.programmes[channel_id] = rows
        return len(rows)

    def fill_missing_numbers(self, platform: str, numbers: dict[str, int]) -> int:
        filled = 0
        for channel_id, lcn in numbers.items():
            channel = self.channels.get(channel_id)
            if channel is not None and platform not in channel.numbers:
                channel.numbers[platform] = lcn
                filled += 1
        return filled

    def prune(self, before: datetime) -> None:
        """Toglie i programmi finiti prima di `before`."""
        for channel_id in list(self.programmes):
            kept = [p for p in self.programmes[channel_id] if p.stop > before]
            if kept:
                self.programmes[channel_id] = kept
            else:
                del self.programmes[channel_id]

    def reuse_from(self, previous: Guide, sources: set[str], after: datetime) -> dict[str, int]:
        """Riprende dalla guida precedente i canali delle fonti indicate
        (quelle fallite) che ora non hanno programmi. Restituisce quanti
        canali per fonte."""
        reused: dict[str, int] = {}
        for channel_id, old in previous.channels.items():
            if channel_id in self.programmes:
                continue
            rows = [p for p in previous.programmes.get(channel_id, []) if p.stop > after and p.source in sources]
            if not rows:
                continue
            for source in sorted({p.source for p in rows}):
                self.add_channel(channel_id, old.name, source, old.numbers, old.logo_urls, old.aliases)
            self.set_programmes(channel_id, rows)
            for source in {p.source for p in rows}:
                reused[source] = reused.get(source, 0) + 1
        return reused

    # --- lettura ---------------------------------------------------------

    def sorted_channels(self, platform: str | None = None) -> list[Channel]:
        """Canali in ordine di numero: della piattaforma scelta, altrimenti del
        digitale terrestre e poi gli altri per nome."""
        if platform:
            chosen = [c for c in self.channels.values() if platform in c.numbers]
            return sorted(chosen, key=lambda c: (c.numbers[platform], c.name.lower()))
        return sorted(
            self.channels.values(),
            key=lambda c: ("dtt" not in c.numbers, c.numbers.get("dtt", 0), c.name.lower()),
        )

    def overlapping(self, channel_id: str, start: datetime, end: datetime) -> list[Programme]:
        """Programmi in onda almeno in parte in [start, end)."""
        return [p for p in self.programmes.get(channel_id, []) if p.stop > start and p.start < end]

    @property
    def programme_count(self) -> int:
        return sum(len(rows) for rows in self.programmes.values())

    # --- istantanea --------------------------------------------------------

    def to_json(self) -> dict:
        return {
            "generated_at": _iso(self.generated_at),
            "channels": [asdict(c) for c in self.channels.values()],
            "programmes": [
                {**asdict(p), "start": _iso(p.start), "stop": _iso(p.stop)}
                for rows in self.programmes.values()
                for p in rows
            ],
        }

    @classmethod
    def from_json(cls, data: dict) -> Guide:
        guide = cls(generated_at=_parse(data["generated_at"]))
        for item in data.get("channels") or []:
            guide.channels[item["id"]] = Channel(**item)
        rows: dict[str, list[Programme]] = {}
        for item in data.get("programmes") or []:
            item = {**item, "start": _parse(item["start"]), "stop": _parse(item["stop"])}
            rows.setdefault(item["channel_id"], []).append(Programme(**item))
        for channel_id, programmes in rows.items():
            guide.set_programmes(channel_id, programmes)
        return guide


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
