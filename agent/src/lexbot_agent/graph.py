"""ReAct-lite LangGraph agent (design D1).

Topology: classify_intent (LLM bound with tool schemas) → conditional edge →
"tools" (ToolNode) or "compose_answer" → compose_answer → END.

Intent classification IS tool selection: the LLM's tool_calls choose the
tool; no tool_calls means out-of-scope → deterministic graceful decline in
compose. Verified against the 0.2 API (StateGraph, START, END, add_node,
add_edge, add_conditional_edges, compile; ToolNode from langgraph.prebuilt).
"""

import json
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from lexbot_ingest.embeddings import build_embedder
from lexbot_ingest.vector_store import VectorStore

from .llm import build_llm
from .state import AgentState
from .tools import build_tools

# Tool name → intent label (AGENT-1).
_INTENT_BY_TOOL = {
    "retrieve_knowledge": "knowledge",
    "search_case": "case",
    "register_follow_up": "follow_up",
    "notify_whatsapp": "notify",
}

OUT_OF_SCOPE_ANSWER = (
    "I can only help with firm knowledge, case files, and follow-ups. "
    "That request is outside my scope."
)

EMPTY_RETRIEVAL_ANSWER = (
    "I couldn't find that information in the firm knowledge base. "
    "A human can follow up with you — shall I notify the team?"
)


def _last_aimessage(state: AgentState) -> AIMessage | None:
    for message in reversed(state["messages"]):
        if isinstance(message, AIMessage):
            return message
    return None


def _tool_call_names(state: AgentState) -> list[str]:
    last = _last_aimessage(state)
    if last is None or not last.tool_calls:
        return []
    return [call.get("name", "") for call in last.tool_calls]


def _parse_tool_payload(tool_message: ToolMessage) -> dict:
    """ToolNode JSON-serializes dict tool outputs into ToolMessage content."""
    if isinstance(tool_message.content, str):
        try:
            return json.loads(tool_message.content)
        except (json.JSONDecodeError, TypeError):
            return {}
    if isinstance(tool_message.content, dict):
        return tool_message.content
    return {}


def _collect_results(state: AgentState) -> list[dict]:
    """Flatten every tool result into one list of {id, text, source, distance}."""
    results: list[dict] = []
    for message in state["messages"]:
        if not isinstance(message, ToolMessage):
            continue
        payload = _parse_tool_payload(message)
        results.extend(payload.get("results", []))
    return results


def build_agent(
    llm: BaseChatModel | None = None,
    store: VectorStore | None = None,
    docs_dir: Path | None = None,
):
    """Build the compiled agent graph.

    llm defaults to build_llm() (gemini/openai/fake via env), store defaults
    to ./data/chroma with the configured embedder. Tests inject a FakeLLM and
    a tmp Chroma store.
    """
    llm = llm or build_llm()
    store = store or VectorStore(path="./data/chroma", embedder=build_embedder())
    tools = build_tools(store, docs_dir=docs_dir)

    def classify_intent(state: AgentState) -> dict:
        response = llm.bind_tools(tools).invoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        return "tools" if _tool_call_names(state) else "compose_answer"

    def compose_answer(state: AgentState) -> dict:
        tool_names = _tool_call_names(state)
        results = _collect_results(state)

        # Out-of-scope: no tool was selected → deterministic decline.
        if not tool_names:
            return {
                "messages": [AIMessage(content=OUT_OF_SCOPE_ANSWER)],
                "intent": "out_of_scope",
                "context": [],
                "sources": [],
                "actions": [],
            }

        intent = _INTENT_BY_TOOL.get(tool_names[0], tool_names[0])

        # Empty retrieval (AGENT-2): state the information is unavailable and
        # offer to notify a human — deterministic, not left to the LLM.
        if not results:
            return {
                "messages": [AIMessage(content=EMPTY_RETRIEVAL_ANSWER)],
                "intent": intent,
                "context": [],
                "sources": [],
                "actions": [{"type": "notify_whatsapp", "detail": "offer to notify a human"}],
            }

        # Success path: compose the answer from the retrieved chunks, citing
        # sources (design data flow: compose_answer invokes the LLM with the
        # tool messages + context).
        sources = [
            {"id": r["id"], "text": r["text"], "source": r["source"], "distance": r["distance"]}
            for r in results
        ]
        context = "\n\n".join(f"[{r['source']}] {r['text']}" for r in results)
        prompt = (
            "You are LexBot, a legal assistant. Answer the user's question "
            "using ONLY the retrieved knowledge below, and cite each source "
            "you use by its [source] tag.\n\n"
            f"Retrieved knowledge:\n{context}"
        )
        final = llm.invoke([HumanMessage(content=prompt)])
        answer = final.content if isinstance(final.content, str) else str(final.content)
        return {
            "messages": [AIMessage(content=answer)],
            "intent": intent,
            "context": [{"results": results}],
            "sources": sources,
            "actions": [{"type": "retrieve_knowledge", "detail": f"{len(results)} chunks retrieved"}],
        }

    workflow = StateGraph(AgentState)
    workflow.add_node("classify_intent", classify_intent)
    workflow.add_node("tools", ToolNode(tools))
    workflow.add_node("compose_answer", compose_answer)
    workflow.add_edge(START, "classify_intent")
    workflow.add_conditional_edges(
        "classify_intent", should_continue, ["tools", "compose_answer"]
    )
    workflow.add_edge("tools", "compose_answer")
    workflow.add_edge("compose_answer", END)
    return workflow.compile()