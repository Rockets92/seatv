"""API HTTP. Avvio: `uvicorn seatv.main:create_app --factory`."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from seatv.config import ROME, Settings
from seatv.db import Database
from seatv.ingest import run_ingest

log = logging.getLogger(__name__)

# dtt = digitale terrestre, tivusat e sky = le due piattaforme satellitari.
Platform = Literal["dtt", "tivusat", "sky"]


class Channel(BaseModel):
    id: str
    name: str
    logo: str | None
    # Numero del canale per piattaforma, es. {"dtt": 1, "tivusat": 1, "sky": 101}.
    numbers: dict[str, int]


class Programme(BaseModel):
    start: datetime
    stop: datetime
    title: str
    description: str | None
    category: str | None
    image: str | None


class Schedule(BaseModel):
    channel: Channel
    date: date
    programmes: list[Programme]


class OnAir(BaseModel):
    channel: Channel
    now: Programme | None
    next: Programme | None


class SourceStatus(BaseModel):
    source: str
    started_at: str
    finished_at: str | None
    channels: int
    programmes: int
    error: str | None


class Health(BaseModel):
    # "degraded" finché non c'è un'ingestione riuscita per ogni fonte.
    status: Literal["ok", "degraded"]
    sources: list[SourceStatus]


def _programme(data: dict) -> Programme:
    return Programme(
        start=data["start"].astimezone(ROME),
        stop=data["stop"].astimezone(ROME),
        title=data["title"],
        description=data["description"],
        category=data["category"],
        image=data["image"],
    )


async def _refresh_loop(settings: Settings, db: Database) -> None:
    while True:
        try:
            await run_ingest(settings, db)
        except Exception:
            log.exception("aggiornamento periodico fallito")
        await asyncio.sleep(settings.refresh_hours * 3600)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if settings.scheduler_enabled:
            task = asyncio.create_task(_refresh_loop(settings, db))
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title="SEA-TV API",
        description="Guida TV dei canali italiani del digitale terrestre (dtt) e del satellite (tivusat, sky).",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.db = db
    app.state.settings = settings

    def get_channel_or_404(channel_id: str) -> Channel:
        channel = db.get_channel(channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="canale non trovato")
        return Channel(**channel)

    @app.get("/health", response_model=Health)
    def health() -> Health:
        runs = db.last_runs()
        healthy = bool(runs) and not any(r["error"] for r in runs)
        return Health(status="ok" if healthy else "degraded", sources=[SourceStatus(**r) for r in runs])

    @app.get("/channels", response_model=list[Channel])
    def list_channels(
        platform: Platform | None = Query(None, description="Solo i canali numerati su questa piattaforma, ordinati per numero"),
    ) -> list[Channel]:
        return [Channel(**c) for c in db.list_channels(platform)]

    @app.get("/channels/{channel_id}", response_model=Channel)
    def get_channel(channel_id: str) -> Channel:
        return get_channel_or_404(channel_id)

    @app.get("/channels/{channel_id}/schedule", response_model=Schedule)
    def schedule(
        channel_id: str,
        day: date | None = Query(None, alias="date", description="Giorno (ora italiana), default oggi"),
    ) -> Schedule:
        channel = get_channel_or_404(channel_id)
        day = day or datetime.now(ROME).date()
        start = datetime.combine(day, time.min, tzinfo=ROME)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=ROME)
        programmes = db.programmes_between(channel_id, start, end)
        return Schedule(channel=channel, date=day, programmes=[_programme(p) for p in programmes])

    @app.get("/channels/{channel_id}/now", response_model=OnAir)
    def channel_now(channel_id: str, at: datetime | None = None) -> OnAir:
        channel = get_channel_or_404(channel_id)
        entry = db.on_air(_instant(at), [channel_id]).get(channel_id, {})
        return _on_air(channel, entry)

    @app.get("/now", response_model=list[OnAir])
    def now_on_air(platform: Platform | None = None, at: datetime | None = None) -> list[OnAir]:
        channels = [Channel(**c) for c in db.list_channels(platform)]
        entries = db.on_air(_instant(at))
        return [_on_air(c, entries.get(c.id, {})) for c in channels]

    return app


def _instant(at: datetime | None) -> datetime:
    if at is None:
        return datetime.now(timezone.utc)
    return at if at.tzinfo else at.replace(tzinfo=ROME)


def _on_air(channel: Channel, entry: dict) -> OnAir:
    return OnAir(
        channel=channel,
        now=_programme(entry["now"]) if "now" in entry else None,
        next=_programme(entry["next"]) if "next" in entry else None,
    )
