"""Thin Bot API client for the inbound webhook path (design D4).

The agent package keeps its own sendMessage call site (the notify_telegram
tool in tools.py); this client is the api package's mirror for webhook
replies and webhook registration. Both sides POST to the same Bot API
endpoints with plain text (no parse_mode, TG-5) through an injected httpx
client so tests run on MockTransport without live Telegram credentials.
"""

import httpx


class TelegramClient:
    """Bot API client: send_message + set_webhook.

    Single attempt, no retry loop (design D3): callers decide how to react to
    non-2xx responses. `token` is the bot token; an empty token means the
    client must never be used (the router/lifespan guard on it).
    """

    def __init__(self, token: str, client: httpx.AsyncClient):
        self.token = token
        self._client = client

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    async def send_message(self, chat_id: int, text: str) -> httpx.Response:
        """Reply to a chat with plain text — no parse_mode (TG-5.1)."""
        return await self._client.post(
            self._url("sendMessage"),
            json={"chat_id": chat_id, "text": text},
            timeout=10.0,
        )

    async def set_webhook(self, url: str, secret_token: str | None = None) -> httpx.Response:
        """Register the webhook URL (idempotent, design D1).

        When a secret_token is configured it is sent so Telegram delivers the
        X-Telegram-Bot-Api-Secret-Token header on every update — without it the
        router fails closed (401) and the webhook can never process updates.
        """
        payload: dict = {"url": url}
        if secret_token:
            payload["secret_token"] = secret_token
        return await self._client.post(
            self._url("setWebhook"),
            json=payload,
            timeout=10.0,
        )
