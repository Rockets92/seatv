"""API HTTP. Avvio: `uvicorn seatv.main:create_app --factory`."""

from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Security
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.security import APIKeyHeader, APIKeyQuery
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from seatv.config import ROME, Settings, http_client as make_http_client
from seatv.db import Database
from seatv.ingest import run_ingest
from seatv.logos import LogoCache

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# dtt = digitale terrestre, tivusat e sky = le due piattaforme satellitari.
Platform = Literal["dtt", "tivusat", "sky"]


class Channel(BaseModel):
    id: str
    name: str
    logo: str | None
    # Numero del canale per piattaforma, es. {"dtt": 1, "tivusat": 1, "sky": 101}.
    numbers: dict[str, int]
    # Fonti che elencano il canale, es. ["sky", "tivu"].
    sources: list[str]


class Programme(BaseModel):
    start: datetime
    stop: datetime
    title: str
    description: str | None
    category: str | None
    image: str | None
    # Fonte da cui arriva il programma.
    source: str


class Schedule(BaseModel):
    channel: Channel
    date: date
    programmes: list[Programme]


class GuideRow(BaseModel):
    channel: Channel
    programmes: list[Programme]


class Guide(BaseModel):
    date: date
    channels: list[GuideRow]


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
    # Giorni di palinsesto scaricati a partire da oggi.
    days_ahead: int


def _programme(data: dict) -> Programme:
    return Programme(
        start=data["start"].astimezone(ROME),
        stop=data["stop"].astimezone(ROME),
        title=data["title"],
        description=data["description"],
        category=data["category"],
        image=data["image"],
        source=data["source"],
    )


async def _refresh_loop(settings: Settings, db: Database) -> None:
    while True:
        try:
            await run_ingest(settings, db)
        except Exception:
            log.exception("aggiornamento periodico fallito")
        await asyncio.sleep(_seconds_to_next_refresh(settings, datetime.now(ROME)))


def _seconds_to_next_refresh(settings: Settings, now: datetime) -> float:
    if settings.refresh_at is None:
        return settings.refresh_hours * 3600
    target = datetime.combine(now.date(), settings.refresh_at, tzinfo=ROME)
    if target <= now:
        target = datetime.combine(now.date() + timedelta(days=1), settings.refresh_at, tzinfo=ROME)
    # In UTC, così i cambi d'ora legale contano.
    return (target.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()


DOCS_HEADER = """
<header class="seatv-docs-header">
  <a href="/" class="seatv-docs-brand"><img src="/static/logo.png" alt="SEA-TV, Simple EPG API"></a>
  <nav><a href="/">Guida TV</a><a href="/openapi.json">openapi.json</a></nav>
</header>
"""


def create_app(settings: Settings | None = None, http_client: httpx.AsyncClient | None = None) -> FastAPI:
    """`http_client` serve ai test per simulare i siti da cui arrivano i loghi."""
    settings = settings or Settings.from_env()
    db = Database(settings.db_path)
    logo_dir = Path(settings.logo_dir) if settings.logo_dir else Path(settings.db_path).parent / "logos"

    def new_client() -> httpx.AsyncClient:
        return http_client or make_http_client(settings)

    def logos() -> LogoCache:
        # Sotto Passenger (WSGI) il lifespan non viene eseguito: la cache nasce alla prima richiesta.
        if getattr(app.state, "logos", None) is None:
            app.state.logos = LogoCache(logo_dir, new_client())
        return app.state.logos

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = new_client()
        app.state.logos = LogoCache(logo_dir, client)
        task = None
        if settings.scheduler_enabled:
            task = asyncio.create_task(_refresh_loop(settings, db))
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if http_client is None:
            await client.aclose()

    app = FastAPI(
        title="SEA-TV API",
        description="Guida TV dei canali italiani del digitale terrestre (dtt) e del satellite (tivusat, sky).",
        version="0.1.0",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "Guida", "description": "Palinsesti: griglia del giorno, programmi di un canale, in onda ora."},
            {"name": "Canali", "description": "Elenco dei canali con numeri per piattaforma e loghi."},
            {"name": "Stato", "description": "Esito dell'ultimo aggiornamento di ogni fonte."},
        ],
        docs_url=None,
        redoc_url=None,
    )
    app.state.db = db
    app.state.settings = settings

    header_key = APIKeyHeader(name="X-API-Key", auto_error=False, description="Chiave di accesso (SEATV_API_KEYS)")
    query_key = APIKeyQuery(name="api_key", auto_error=False, description="In alternativa all'header X-API-Key")

    def require_key(header: str | None = Security(header_key), query: str | None = Security(query_key)) -> None:
        given = (header or query or "").encode()
        if not any(hmac.compare_digest(given, key.encode()) for key in settings.api_keys):
            raise HTTPException(status_code=401, detail="chiave API mancante o non valida")

    # Le rotte con i dati della guida; con SEATV_API_KEYS impostata richiedono la chiave.
    api = APIRouter(dependencies=[Depends(require_key)] if settings.api_keys else [])

    def get_channel_or_404(channel_id: str) -> Channel:
        channel = db.get_channel(channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="canale non trovato")
        return Channel(**channel)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/docs", include_in_schema=False)
    def docs() -> HTMLResponse:
        page = get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title="SEA-TV API · Documentazione",
            swagger_favicon_url="/static/icon-192.png",
            swagger_ui_parameters={
                "syntaxHighlight": {"theme": "monokai"},
                "defaultModelsExpandDepth": 0,
                "displayRequestDuration": True,
                "tryItOutEnabled": True,
            },
        )
        html = page.body.decode()
        html = html.replace("</head>", '<link rel="stylesheet" href="/static/docs.css">\n<meta name="theme-color" content="#020817">\n</head>', 1)
        html = html.replace("<body>", "<body>" + DOCS_HEADER, 1)
        return HTMLResponse(html)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "favicon.ico")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @api.get("/health", response_model=Health, tags=["Stato"])
    def health() -> Health:
        runs = db.last_runs()
        healthy = bool(runs) and not any(r["error"] for r in runs)
        return Health(
            status="ok" if healthy else "degraded",
            sources=[SourceStatus(**r) for r in runs],
            days_ahead=settings.days_ahead,
        )

    @api.get("/channels", response_model=list[Channel], tags=["Canali"])
    def list_channels(
        platform: Platform | None = Query(None, description="Solo i canali numerati su questa piattaforma, ordinati per numero"),
    ) -> list[Channel]:
        return [Channel(**c) for c in db.list_channels(platform)]

    @api.get("/channels/{channel_id}", response_model=Channel, tags=["Canali"])
    def get_channel(channel_id: str) -> Channel:
        return get_channel_or_404(channel_id)

    @app.get(
        "/channels/{channel_id}/logo",
        tags=["Canali"],
        response_class=FileResponse,
        responses={
            200: {"content": {"image/png": {}}},
            307: {"description": "Il server non è riuscito a scaricarlo: il browser lo chiede alla fonte"},
            404: {"description": "Canale senza logo"},
        },
    )
    async def channel_logo(channel_id: str) -> Response:
        """Logo del canale, scaricato dalla fonte la prima volta e poi servito dalla cache."""
        channel = get_channel_or_404(channel_id)
        urls = db.logo_candidates(channel.id)
        cached = await logos().get(channel.id, urls) if urls else None
        if cached is None:
            # Ultimo tentativo dal browser, che la fonte potrebbe accettare.
            target = logos().redirect_target(urls)
            if target is None:
                raise HTTPException(status_code=404, detail="logo non disponibile")
            return RedirectResponse(target, status_code=307)
        path, media_type = cached
        return FileResponse(path, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})

    @api.get("/channels/{channel_id}/schedule", response_model=Schedule, tags=["Guida"])
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

    @api.get("/guide", response_model=Guide, tags=["Guida"])
    def guide(
        day: date | None = Query(None, alias="date", description="Giorno (ora italiana), default oggi"),
        platform: Platform | None = None,
    ) -> Guide:
        """Tutti i canali con i programmi in onda nel giorno, anche solo in parte:
        i dati per una griglia stile guida TV."""
        day = day or datetime.now(ROME).date()
        start = datetime.combine(day, time.min, tzinfo=ROME)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=ROME)
        programmes = db.programmes_overlapping(start, end)
        rows = [
            GuideRow(channel=Channel(**c), programmes=[_programme(p) for p in programmes.get(c["id"], [])])
            for c in db.list_channels(platform)
        ]
        return Guide(date=day, channels=rows)

    @api.get("/channels/{channel_id}/now", response_model=OnAir, tags=["Guida"])
    def channel_now(channel_id: str, at: datetime | None = None) -> OnAir:
        channel = get_channel_or_404(channel_id)
        entry = db.on_air(_instant(at), [channel_id]).get(channel_id, {})
        return _on_air(channel, entry)

    @api.get("/now", response_model=list[OnAir], tags=["Guida"])
    def now_on_air(platform: Platform | None = None, at: datetime | None = None) -> list[OnAir]:
        channels = [Channel(**c) for c in db.list_channels(platform)]
        entries = db.on_air(_instant(at))
        return [_on_air(c, entries.get(c.id, {})) for c in channels]

    app.include_router(api)
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
