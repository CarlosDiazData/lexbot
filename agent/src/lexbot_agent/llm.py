"""LLM wiring: build_llm provider factory + FakeLLM for tests.

Mirrors ingest's build_embedder (design D3): a provider string selects the
langchain-core chat model wrapper. FakeLLM lives here exactly like
FakeEmbedder lives in ingest's embeddings.py — test-only, deterministic.
"""

import logging
import os

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class FakeLLM(BaseChatModel):
    """Scripted chat model for tests (never use in production).

    Returns its scripted responses in order, one per invoke. bind_tools is a
    no-op: the scripted AIMessages already carry any tool_calls, so tests
    control the tool-calling path directly (design open question, resolved).
    """

    responses: list[BaseMessage]
    _index: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        if self._index >= len(self.responses):
            raise ValueError("FakeLLM ran out of scripted responses")
        message = self.responses[self._index]
        self._index += 1
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        # Scripted responses already encode the tool calls we want.
        return self


def build_llm(provider: str | None = None) -> BaseChatModel:
    """Build a chat model from a provider name (gemini | openai | fake).

    Defaults to gemini via the LLM_PROVIDER env var, matching build_embedder.
    """
    provider = provider or os.getenv("LLM_PROVIDER", "gemini")
    model = os.getenv("LLM_MODEL")
    if provider == "gemini":
        # ChatGoogleGenerativeAI reads GOOGLE_API_KEY by default, but the
        # project documents GEMINI_API_KEY (same key, new-genai SDK name).
        # Accept either and pass it explicitly so the documented .env works.
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning(
                "LLM_PROVIDER=gemini but GEMINI_API_KEY/GOOGLE_API_KEY is unset — falling "
                "back to FakeLLM (deterministic decline; set GEMINI_API_KEY for real answers)"
            )
            return FakeLLM(responses=[AIMessage(content="")])
        return ChatGoogleGenerativeAI(
            model=model or DEFAULT_GEMINI_MODEL,
            temperature=0,
            google_api_key=api_key,
            max_retries=2,
        )
    if provider == "openai":
        if not os.getenv("OPENAI_API_KEY"):
            logger.warning(
                "LLM_PROVIDER=openai but OPENAI_API_KEY is unset — falling back to FakeLLM "
                "(deterministic decline; set OPENAI_API_KEY for real answers)"
            )
            return FakeLLM(responses=[AIMessage(content="")])
        return ChatOpenAI(model=model or DEFAULT_OPENAI_MODEL, temperature=0)
    if provider == "fake":
        return FakeLLM(responses=[])
    raise ValueError(f"Unknown LLM provider: {provider}")