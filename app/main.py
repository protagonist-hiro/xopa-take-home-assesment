import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.redis_client import close_redis
from app.routers import calls, metrics
from app.routers import debug_ui

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up – initialising database…")
    await init_db()
    logger.info("Ready.")
    yield
    logger.info("Shutting down – closing Redis connection…")
    await close_redis()


app = FastAPI(
    title="Mock Communication Service",
    version="1.0.0",
    description=(
        "Async REST + WebSocket service simulating a calling platform. "
        "All endpoints require Authorization: Bearer <API_KEY>."
    ),
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS – allow the debug HTML served from any origin during development
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve locally written recordings when STORAGE_BACKEND=local.
if settings.STORAGE_BACKEND.lower().strip() == "local":
    recordings_dir = Path(settings.LOCAL_RECORDINGS_DIR)
    recordings_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/recordings", StaticFiles(directory=str(recordings_dir)), name="recordings")


# ---------------------------------------------------------------------------
# Custom 429 handler: always return the canonical error envelope
# ---------------------------------------------------------------------------
@app.exception_handler(429)
async def _rate_limit_handler(request: Request, exc):
    return JSONResponse(status_code=429, content={"error": "Rate limit exceeded"})


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(calls.router, tags=["calls"])
app.include_router(metrics.router, tags=["metrics"])

# Debug UI – only available when DEBUG=true
if settings.DEBUG:
    app.include_router(debug_ui.router, tags=["debug"])
    logger.info("Debug UI enabled → GET /debug?key=<ADMIN_KEY>")


@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}
