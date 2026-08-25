"""POST /webhook/telegram — inbound Telegram updates (TG-1).

Telegram delivers updates to the registered webhook URL (D1). The
X-Telegram-Bot-Api-Secret-Token header is compared against
TELEGRAM_WEBHOOK_SECRET with hmac.compare_digest and FAILS CLOSED: an unset
secret rejects every update (D5/TG-1.2). Valid text updates get a fast 200
with the agent run and the reply to the sender deferred to BackgroundTasks
(TG-1.1); update_ids are deduplicated in a bounded FIFO cache so Telegram
retries never double-reply (D2/TG-1.3). Non-message updates are acknowledged
but not processed (TG-1.4). The envelope is a raw dict — no pydantic model.
"""

import hmac
import logging
from collections import OrderedDict
from threading import Lock
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage

from ..telegram import TelegramClient

logger = logging.getLogger(__name__)

router = APIRouter()

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


class UpdateIdCache:
    """Bounded FIFO cache of processed update_ids (design D2).

    Telegram update_ids are globally increasing, so FIFO eviction at maxsize
    is correct. Thread-safe: check-and-record happens under one lock, so two
    concurrent deliveries of the same update cannot both pass.
    """

    def __init__(self, maxsize: int = 1000):
        self._maxsize = maxsize
        self._ids: OrderedDict[int, None] = OrderedDict()
        self._lock = Lock()

    def check(self, update_id: int) -> bool:
        """Record update_id and return True when it was already seen."""
        with self._lock:
            if update_id in self._ids:
                return True
            self._ids[update_id] = None
            while len(self._ids) > self._maxsize:
                self._ids.popitem(last=False)
            return False


async def _run_agent_and_reply(
    agent: Any, client: TelegramClient, chat_id: int, text: str
) -> None:
    """Run the agent on the inbound text and reply to the sender's chat (TG-1.1).

    Runs in BackgroundTasks after the fast 200. A failed agent run or a
    failed send is logged and dropped — never re-raised, so the webhook
    response is unaffected (v1: no retry loop, no error replies).
    """
    try:
        result = await agent.ainvoke({"messages": [HumanMessage(content=text)]})
    except Exception:
        logger.exception("telegram webhook: agent run failed for chat %s", chat_id)
        return
    final_message = result["messages"][-1]
    answer = (
        final_message.content
        if isinstance(final_message.content, str)
        else str(final_message.content)
    )
    try:
        await client.send_message(chat_id, answer)
    except Exception:
        logger.exception("telegram webhook: reply to chat %s failed", chat_id)


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    state = request.app.state

    # D5/TG-1.2: fail closed — an unset or mismatched secret rejects every
    # update before any parsing or processing happens.
    provided = request.headers.get(SECRET_HEADER, "")
    if not state.telegram_secret or not hmac.compare_digest(
        provided, state.telegram_secret
    ):
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "unauthorized",
                    "message": "Invalid or missing X-Telegram-Bot-Api-Secret-Token",
                    "retryable": False,
                }
            },
        )

    # TG-3.1/D5 stub mode: no bot token → acknowledge, never process or reply.
    if not state.telegram_client.token:
        return {"ok": True}

    body = await request.json()

    # D2/TG-1.3: dedup before processing — a Telegram retry (or a concurrent
    # duplicate delivery) of a recorded update_id is acknowledged and dropped.
    if state.telegram_dedup.check(body["update_id"]):
        return {"ok": True}

    # TG-1.4: non-message updates are acknowledged but not processed.
    message = body.get("message") or {}
    if not message.get("text"):
        return {"ok": True}

    # TG-1.1: fast 200 now; the agent run and the reply happen in the
    # background so Telegram's webhook timeout is never hit.
    background_tasks.add_task(
        _run_agent_and_reply,
        state.agent,
        state.telegram_client,
        message["chat"]["id"],
        message["text"],
    )
    return {"ok": True}
