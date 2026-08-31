"""App factory with dependency injection (design D4/D5/D6).

create_app(agent, store, db, knowledge_dir) builds a FastAPI app where every
runtime dependency is injectable: tests pass fake agent/store/db objects and a
tmp knowledge dir; production defaults come from env (DATABASE_URL,
LLM_PROVIDER, ...) and repo-root paths.

Lifespan:
- D5: apply db/init.sql idempotently via the Database seam (CREATE TABLE IF
  NOT EXISTS — re-running never errors or duplicates, DB-1).
- D6: auto-seed the knowledge store once at startup when store.count() == 0.
- D1: guarded fail-soft setWebhook — only when TELEGRAM_BOT_TOKEN AND
  TELEGRAM_WEBHOOK_URL are set; failures log and keep the app booting.

Error envelope (design): every unhandled request error becomes
{"error": {"code", "message", "retryable"}}. LLM/agent failures inside
/chat are re-raised as LLMUnavailableError -> HTTP 503 retryable (API-1);
anything else -> HTTP 500 non-retryable.
"""

import logging
import os
import random
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from lexbot_agent.graph import build_agent
from lexbot_agent.tools import Database, seed_knowledge
from lexbot_ingest.vector_store import PgVectorStore, VectorStore, build_store

from .telegram import TelegramClient
from .routers.telegram import UpdateIdCache

logger = logging.getLogger(__name__)

# repo_root/docs/knowledge and repo_root/ui/dist — api/src/lexbot_api/app.py
# -> parents[3] == repo root (also /app when copied into the Docker image).
DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "docs" / "knowledge"
UI_DIST_DIR = Path(__file__).resolve().parents[3] / "ui" / "dist"


class LLMUnavailableError(Exception):
    """The agent/LLM call failed (API-1 scenario). Mapped to HTTP 503 with a
    retry hint by the global exception handler."""

    code = "llm_unavailable"
    retryable = True


def _wait_for_db(
    database: Database,
    attempts: int = 36,
    base_delay: float = 10,
    max_delay: float = 30,
) -> None:
    """Block until the database is reachable (PGV-3, RDS-not-ready).

    Bounded retry: exponential backoff + jitter between pings, ~10 min budget
    with the defaults. On exhaustion logs CRITICAL and raises — uvicorn exits
    non-zero so ECS restarts the task (the outer retry loop). Tests inject
    small attempts/delays.
    """
    delay = base_delay
    for attempt in range(1, attempts + 1):
        if database.ping():
            logger.info("database reachable after %d attempt(s)", attempt)
            return
        if attempt == attempts:
            break
        time.sleep(delay * random.uniform(0.5, 1.5))
        delay = min(delay * 1.5, max_delay)
    logger.critical(
        "database unreachable after %d attempts; raising so the task restarts",
        attempts,
    )
    raise RuntimeError("database unreachable at startup")


def get_agent(request: Request) -> Any:
    return request.app.state.agent


def get_store(request: Request) -> VectorStore:
    return request.app.state.store


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_knowledge_dir(request: Request) -> Path:
    return request.app.state.knowledge_dir


def create_app(
    agent: Any = None,
    store: VectorStore | None = None,
    db: Database | None = None,
    knowledge_dir: Path | None = None,
    telegram_http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Build the app. agent/store/db/knowledge_dir injectable for tests.

    agent defaults to the compiled LangGraph agent (env LLM provider, shared
    store + db); store defaults to ./data/chroma with the configured embedder;
    db defaults to Database() (DATABASE_URL); knowledge_dir defaults to
    docs/knowledge (auto-seed source, D6); telegram_http_client defaults to a
    real httpx.AsyncClient and is injectable so tests run the TelegramClient
    on MockTransport (design D4).
    """
    load_dotenv()  # DEV parity with the ingest CLI: honor .env.example

    # API-4 / D9: CORS origins from a comma-separated CORS_ORIGINS env var,
    # defaulting to the Vite dev server. Read after load_dotenv() so the env
    # file is honored; strip whitespace and skip empty entries.
    cors_origins = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    ]

    store = store or build_store()
    database = db or Database()
    knowledge = knowledge_dir or DEFAULT_KNOWLEDGE_DIR
    agent = agent or build_agent(store=store, db=database)

    # TG-3/D7: Telegram inbound wiring. Empty env defaults keep the stack
    # booting in stub mode: no secret → webhook rejects every update (fail
    # closed, D5); no token → webhook acknowledges but never processes
    # (TG-3.1); no URL → lifespan skips setWebhook (D1).
    telegram_client = TelegramClient(
        token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        client=telegram_http_client or httpx.AsyncClient(),
    )
    telegram_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    telegram_webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # PGV-3: the pgvector store needs the database reachable before any
        # schema apply or seed. Bounded retry absorbs RDS-not-ready at first
        # deploy; exhaustion raises -> uvicorn exits non-zero -> ECS restarts.
        if isinstance(store, PgVectorStore):
            _wait_for_db(database)
        # D5: idempotent schema bootstrap (also covers pre-existing db-data
        # volumes that never saw the compose initdb mount). For pgvector this
        # creates the extension + legal_kb_embeddings DDL (db/init.sql).
        database.apply_schema()
        # D6 auto-seed. Chroma keeps the count()==0 gate; the pgvector path
        # validates dimensions and seeds unconditionally — chunk_id UNIQUE + ON CONFLICT
        # DO NOTHING make re-runs insert nothing, and a mid-seed crash resumes cleanly
        # on the next restart (PGV-4: never partial data, no duplicates).
        if isinstance(store, PgVectorStore):
            store.validate_dimensions()
            seed_knowledge(store, knowledge)
        elif store.count() == 0:
            seed_knowledge(store, knowledge)
        # D1: guarded fail-soft setWebhook — only when both the bot token and
        # the webhook URL are configured; any failure logs and keeps booting.
        telegram: TelegramClient = app.state.telegram_client
        webhook_url: str = app.state.telegram_webhook_url
        if telegram.token and webhook_url:
            try:
                response = await telegram.set_webhook(
                    webhook_url, secret_token=app.state.telegram_secret
                )
                if response.status_code >= 400:
                    logger.warning(
                        "setWebhook rejected by Telegram (HTTP %s): %s",
                        response.status_code,
                        response.text,
                    )
            except httpx.HTTPError:
                logger.warning(
                    "setWebhook failed; continuing without webhook registration",
                    exc_info=True,
                )
        yield

    app = FastAPI(title="LexBot API", version="0.1.0", lifespan=lifespan)
    app.state.agent = agent
    app.state.store = store
    app.state.db = database
    app.state.knowledge_dir = knowledge
    app.state.telegram_client = telegram_client
    app.state.telegram_secret = telegram_secret
    app.state.telegram_webhook_url = telegram_webhook_url
    app.state.telegram_dedup = UpdateIdCache()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=False,  # no cookies in M3 (D9)
    )

    app.add_exception_handler(
        LLMUnavailableError,
        lambda request, exc: JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "retryable": exc.retryable,
                }
            },
        ),
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # Last-resort envelope; specific handlers (LLMUnavailableError,
        # HTTPException, RequestValidationError) win via MRO lookup.
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Internal server error",
                    "retryable": False,
                }
            },
        )

    # Routers are imported inside the factory to avoid the app <-> router
    # import cycle (routers import the dependency getters from ..app).
    from .routers import chat, health, ingest, telegram

    app.include_router(chat.router)
    app.include_router(ingest.router)
    app.include_router(health.router)
    app.include_router(telegram.router)

    # INF-4: serve the built UI from the container, same-origin. Mounted AFTER
    # the routers so /health, /webhook/*, /chat keep winning; the catch-all
    # root mount only serves unmatched paths (/ , /assets/*). Guarded so dev
    # runs without a build just skip it.
    if UI_DIST_DIR.exists():
        app.mount("/", StaticFiles(directory=UI_DIST_DIR, html=True))

    return app
