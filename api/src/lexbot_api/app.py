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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from lexbot_agent.graph import build_agent
from lexbot_agent.tools import Database, seed_knowledge
from lexbot_ingest.embeddings import build_embedder
from lexbot_ingest.vector_store import VectorStore

from .telegram import TelegramClient
from .routers.telegram import UpdateIdCache

logger = logging.getLogger(__name__)

# repo_root/docs/knowledge and repo_root/data/chroma — api/src/lexbot_api/app.py
# -> parents[3] == repo root (also /app when copied into the Docker image).
DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "docs" / "knowledge"
DEFAULT_CHROMA_PATH = str(Path(__file__).resolve().parents[3] / "data" / "chroma")


class LLMUnavailableError(Exception):
    """The agent/LLM call failed (API-1 scenario). Mapped to HTTP 503 with a
    retry hint by the global exception handler."""

    code = "llm_unavailable"
    retryable = True


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

    store = store or VectorStore(path=DEFAULT_CHROMA_PATH, embedder=build_embedder())
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
        # D5: idempotent schema bootstrap (also covers pre-existing db-data
        # volumes that never saw the compose initdb mount).
        database.apply_schema()
        # D6: auto-seed knowledge once when the store is empty.
        if store.count() == 0:
            seed_knowledge(store, knowledge)
        # D1: guarded fail-soft setWebhook — only when both the bot token and
        # the webhook URL are configured; any failure logs and keeps booting.
        telegram: TelegramClient = app.state.telegram_client
        webhook_url: str = app.state.telegram_webhook_url
        if telegram.token and webhook_url:
            try:
                response = await telegram.set_webhook(webhook_url)
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

    return app
