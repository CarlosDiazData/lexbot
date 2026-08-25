"""Agent tools. TOOL-5 contract: every tool returns structured JSON (a dict),
never free text — ToolNode wraps the dict into a JSON ToolMessage.

WU2 shipped retrieve_knowledge (TOOL-1); WU3 adds search_case (TOOL-2),
register_follow_up (TOOL-3) and notify_telegram (TOOL-4). build_tools is a
factory so tests can inject a tmp Chroma store + FakeEmbedder and a fake
Database / httpx transport (design D4 DI pattern).

The SQL tools talk to PostgreSQL through the Database class — the single
testable seam. Production connects via DATABASE_URL; tests inject a duck-typed
fake whose methods raise real psycopg exceptions. DB failures are translated
to error JSON (TOOL-5) so the agent answers gracefully instead of crashing.
"""

import os
from pathlib import Path

import httpx
import psycopg
from langchain_core.tools import tool

from lexbot_ingest.chunker import chunk_text
from lexbot_ingest.cli import load_docs
from lexbot_ingest.vector_store import VectorStore

# repo_root/docs/knowledge and repo_root/db/init.sql —
# agent/src/lexbot_agent/tools.py → parents[3]
DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "docs" / "knowledge"
DEFAULT_INIT_SQL = Path(__file__).resolve().parents[3] / "db" / "init.sql"

RETRIEVAL_TOP_K = 3

# Matches the compose db service (docker-compose.yml) and db/init.sql DDL.
DEFAULT_DATABASE_URL = "postgresql://lexbot:lexbot@localhost:5432/lexbot"


class CaseNotFoundError(Exception):
    """register_follow_up referenced a case_number that does not exist."""


class Database:
    """psycopg3 access layer for the SQL tools (TOOL-2, TOOL-3).

    `_connect` is the only seam: production opens a connection from DATABASE_URL,
    tests monkeypatch it or inject a duck-typed fake db into build_tools. All
    methods raise psycopg.Error on failure — the tools translate that into
    error JSON so the graph continues (TOOL-5, DB-down scenario).
    """

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

    def _connect(self):
        return psycopg.connect(self.dsn)

    def search_cases(self, query: str) -> list[dict]:
        """Case rows matching case_number or client_name (case-insensitive)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT case_number, client_name, status, summary "
                    "FROM cases "
                    "WHERE case_number ILIKE %s OR client_name ILIKE %s "
                    "ORDER BY id LIMIT 10",
                    (f"%{query}%", f"%{query}%"),
                )
                return [
                    {
                        "case_number": row[0],
                        "client_name": row[1],
                        "status": row[2],
                        "summary": row[3],
                    }
                    for row in cur.fetchall()
                ]

    def insert_follow_up(
        self, case_number: str, description: str, due_date: str | None
    ) -> int:
        """Insert a follow_ups row for the case identified by case_number and
        return its new id. Raises CaseNotFoundError for unknown case numbers.
        The connection context manager commits the INSERT on success.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM cases WHERE case_number = %s", (case_number,))
                case = cur.fetchone()
                if case is None:
                    raise CaseNotFoundError(case_number)
                cur.execute(
                    "INSERT INTO follow_ups (case_id, description, due_date) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (case[0], description, due_date),
                )
                return cur.fetchone()[0]

    def apply_schema(self, init_sql: Path | None = None) -> None:
        """Apply db/init.sql idempotently (design D5, DB-1).

        The file is split on ';' and each statement executed separately:
        psycopg3's cursor.execute sends one statement per call, and the DDL
        uses CREATE TABLE IF NOT EXISTS, so re-running never errors or
        duplicates. The connection context manager commits on success.
        """
        sql = (init_sql or DEFAULT_INIT_SQL).read_text(encoding="utf-8")
        with self._connect() as conn:
            with conn.cursor() as cur:
                for statement in sql.split(";"):
                    statement = statement.strip()
                    if statement:
                        cur.execute(statement)

    def ping(self) -> bool:
        """Lightweight reachability check (SELECT 1). False on psycopg error —
        used by the API health endpoint without failing the request."""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            return True
        except psycopg.Error:
            return False


def seed_knowledge(store: VectorStore, docs_dir: Path) -> int:
    """Ingest docs/knowledge into the store (design D6 auto-seed). Returns the
    number of chunks added. Idempotent by contract: caller only seeds when
    store.count() == 0.
    """
    total = 0
    for source, text in load_docs(docs_dir):
        chunks = chunk_text(text, source=source)
        store.add_chunks(chunks)
        total += len(chunks)
    return total


def build_tools(
    store: VectorStore,
    docs_dir: Path | None = None,
    db: Database | None = None,
    http_client: httpx.Client | None = None,
    bot_token: str | None = None,
    chat_id: str | None = None,
) -> list:
    """Build the tool list bound to concrete store / db / http dependencies.

    docs_dir overrides the auto-seed source (defaults to docs/knowledge);
    tests pass an empty dir to exercise the empty-retrieval path. db defaults
    to Database() (DATABASE_URL); http_client defaults to a real httpx.Client;
    bot_token / chat_id default to the TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
    env vars (design D7).
    """
    knowledge_dir = docs_dir or DEFAULT_KNOWLEDGE_DIR
    database = db or Database()
    client = http_client or httpx.Client()
    token = bot_token if bot_token is not None else os.getenv("TELEGRAM_BOT_TOKEN")
    default_chat_id = chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID")

    @tool
    def retrieve_knowledge(query: str) -> dict:
        """Retrieve relevant firm knowledge chunks for a legal question. Use
        when the user asks about firm policies, client FAQs, or contract
        terms. Returns ranked chunks with source metadata."""
        # D6: dev convenience — seed once when the collection is empty so a
        # fresh store still answers. Seeding produced nothing (e.g. no docs
        # dir) -> empty retrieval, which the graph turns into a decline.
        if store.count() == 0:
            seed_knowledge(store, knowledge_dir)
        if store.count() == 0:
            return {"results": []}
        results = store.query(query, n_results=RETRIEVAL_TOP_K)
        return {
            "results": [
                {
                    "id": row["id"],
                    "text": row["text"],
                    "source": row["metadata"]["source"],
                    "distance": row["distance"],
                }
                for row in results
            ]
        }

    @tool
    def search_case(query: str) -> dict:
        """Search case files by case number or client name. Returns matching
        cases with their status and summary. Use when the user asks about a
        specific case or client matter."""
        try:
            cases = database.search_cases(query)
        except psycopg.Error as exc:
            # TOOL-5: DB down -> error JSON; the agent answers gracefully.
            return {
                "error": {
                    "code": "db_unavailable",
                    "message": f"Case search unavailable: {exc}",
                    "retryable": True,
                }
            }
        return {"cases": cases}

    @tool
    def register_follow_up(
        case_number: str, description: str, due_date: str | None = None
    ) -> dict:
        """Register a follow-up task on a case. Use when the user asks to
        schedule a reminder or follow-up for a client matter."""
        try:
            new_id = database.insert_follow_up(case_number, description, due_date)
        except CaseNotFoundError:
            return {
                "error": {
                    "code": "case_not_found",
                    "message": f"No case with number {case_number}",
                    "retryable": False,
                }
            }
        except psycopg.Error as exc:
            return {
                "error": {
                    "code": "db_unavailable",
                    "message": f"Follow-up registration unavailable: {exc}",
                    "retryable": True,
                }
            }
        return {"id": new_id}

    @tool
    def notify_telegram(chat_id: str = "", message: str = "") -> dict:
        """Notify a human via Telegram (Bot API sendMessage, D7 stub). When no
        TELEGRAM_BOT_TOKEN is configured this is a no-op so flows still work
        in dev; no real Telegram send ever happens here."""
        if not token:
            return {"status": "stub"}
        target = chat_id or default_chat_id
        if not target:
            return {
                "error": {
                    "code": "chat_id_missing",
                    "message": "No chat_id given and TELEGRAM_CHAT_ID is not set",
                    "retryable": False,
                }
            }
        try:
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": target, "text": message},
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            return {
                "error": {
                    "code": "telegram_unreachable",
                    "message": f"Telegram notify unavailable: {exc}",
                    "retryable": True,
                }
            }
        if response.status_code == 429:
            # TG-2.3: single attempt, no retry loop — surface retry_after so
            # the agent answers gracefully (design D3).
            try:
                retry_after = response.json().get("parameters", {}).get("retry_after", 0)
            except ValueError:
                retry_after = 0
            return {
                "error": {
                    "code": "telegram_rate_limited",
                    "message": f"Telegram rate limited (retry after {retry_after}s)",
                    "retryable": True,
                    "retry_after": retry_after,
                }
            }
        if response.status_code == 400 and "chat not found" in response.text.lower():
            return {
                "error": {
                    "code": "chat_not_found",
                    "message": "Telegram: chat not found",
                    "retryable": False,
                }
            }
        if response.status_code >= 400:
            return {
                "error": {
                    "code": "telegram_unreachable",
                    "message": f"Telegram notify unavailable (HTTP {response.status_code})",
                    "retryable": True,
                }
            }
        return {"status": "sent"}

    return [retrieve_knowledge, search_case, register_follow_up, notify_telegram]