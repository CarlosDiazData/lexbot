"""AgentState: the shared state schema for the LangGraph agent.

Per design D2 — a custom TypedDict instead of MessagesState so intent,
context, sources, and actions survive alongside the message list.
"""

from operator import add
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    # Message list is reduced with operator.add so every node appends
    # rather than overwrites.
    messages: Annotated[list[BaseMessage], add]
    # Classified intent: knowledge | case | follow_up | notify | out_of_scope.
    intent: str
    # Tool payloads the answer was composed from (e.g. retrieved chunks).
    context: list[dict]
    # Cited sources in ChatResponse shape: {id, text, source, distance}.
    sources: list[dict]
    # Side effects / offers, ChatResponse shape: {type, detail}.
    actions: list[dict]