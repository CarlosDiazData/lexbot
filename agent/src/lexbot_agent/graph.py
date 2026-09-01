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
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from lexbot_ingest.embeddings import build_embedder
from lexbot_ingest.vector_store import VectorStore

from .llm import build_llm
from .state import AgentState
from .tools import build_tools

LEXBOT_SYSTEM_PROMPT = (
    "You are LexBot, a warm, helpful, empathetic, and professional legal assistant for a law firm.\n"
    "Your purpose is to guide clients and answer questions about firm policies, legal services, "
    "contract reviews, client FAQs, case status, and consultation options.\n\n"
    "Guidelines:\n"
    "- When the user greets you or starts a conversation, reply warmly in the user's language and invite them to share their legal questions or situation.\n"
    "- When the user discusses a situation or legal problem, listen empathetically, provide helpful guidance on available options, or use your tools to retrieve knowledge or case information.\n"
    "- Use the `retrieve_knowledge` tool whenever answering specific questions about firm policies, fees, timelines, services, or FAQs.\n"
    "- Use the `search_case` tool when looking up specific case numbers or client matters.\n"
    "- If the user asks for something completely outside legal assistance or the law firm (e.g. cooking recipes, general jokes, sports), politely decline and state that you specialize in legal assistance for the firm.\n"
    "- Always maintain a respectful, reassuring, and clear tone."
)

# Tool name → intent label (AGENT-1).
_INTENT_BY_TOOL = {
    "retrieve_knowledge": "knowledge",
    "search_case": "case",
    "register_follow_up": "follow_up",
    "notify_telegram": "notify",
}

OUT_OF_SCOPE_ANSWER = (
    "I can only help with firm knowledge, case files, and follow-ups. "
    "That request is outside my scope."
)

EMPTY_RETRIEVAL_ANSWER = (
    "I couldn't find that information in the firm knowledge base. "
    "A human can follow up with you — shall I notify the team?"
)

# TOOL-5: error JSON payloads are surfaced gracefully — one deterministic
# answer per error code so the agent continues instead of crashing.
_ERROR_ANSWERS = {
    "db_unavailable": (
        "The case database is temporarily unavailable. "
        "Please try again in a moment."
    ),
    "case_not_found": (
        "I couldn't find that case number in the case files. "
        "Double-check the number, or ask a human to create the case first."
    ),
    "telegram_rate_limited": (
        "Telegram is rate-limiting notifications right now. "
        "Please try again in a moment."
    ),
    "chat_not_found": (
        "I couldn't send the notification: that chat doesn't exist. "
        "Double-check the chat ID."
    ),
    "chat_id_missing": (
        "I couldn't send the notification: no chat is configured to notify."
    ),
    "telegram_unreachable": (
        "The Telegram notification service is unreachable right now. "
        "Please try again in a moment."
    ),
}


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
    """Flatten every knowledge-tool result into one list of
    {id, text, source, distance} (retrieve_knowledge payloads only)."""
    results: list[dict] = []
    for message in state["messages"]:
        if not isinstance(message, ToolMessage):
            continue
        payload = _parse_tool_payload(message)
        results.extend(payload.get("results", []))
    return results


def _tool_payloads(state: AgentState) -> list[dict]:
    """Every non-empty ToolMessage payload in message order.

    Used by non-knowledge intents (case / follow_up / notify) to summarize
    the tool's JSON payload, and to surface error JSON gracefully (TOOL-5).
    """
    payloads: list[dict] = []
    for message in state["messages"]:
        if isinstance(message, ToolMessage):
            payload = _parse_tool_payload(message)
            if payload:
                payloads.append(payload)
    return payloads


def _compose_from_tool_payload(tool_name: str, intent: str, payloads: list[dict]) -> dict:
    """Deterministic answer for non-knowledge tool intents (case, follow_up,
    notify): summarize the tool's JSON payload in the answer; surface error
    JSON gracefully. Sources stay empty — no retrieval was used (AGENT-2)."""
    errors = [p["error"] for p in payloads if "error" in p]
    if errors:
        code = errors[0].get("code", "unknown")
        answer = _ERROR_ANSWERS.get(code, f"Something went wrong: {code}.")
        return {
            "messages": [AIMessage(content=answer)],
            "intent": intent,
            "context": [{"error": errors[0]}],
            "sources": [],
            "actions": [{"type": tool_name, "detail": f"error: {code}"}],
        }

    if not payloads:
        return {
            "messages": [AIMessage(content="The tool didn't return a usable result.")],
            "intent": intent,
            "context": [],
            "sources": [],
            "actions": [{"type": tool_name, "detail": "no payload"}],
        }

    if intent == "case":
        cases = [c for p in payloads for c in p.get("cases", [])]
        if not cases:
            answer = "I couldn't find any matching cases in the case files."
            detail = "no cases found"
        else:
            lines = [
                f"- {c['case_number']} — {c.get('client_name', '?')} ({c.get('status', '?')})"
                + (f": {c['summary']}" if c.get("summary") else "")
                for c in cases
            ]
            heading = "Found this case:" if len(cases) == 1 else f"Found {len(cases)} cases:"
            answer = f"{heading}\n" + "\n".join(lines)
            detail = f"{len(cases)} case(s) found"
        return {
            "messages": [AIMessage(content=answer)],
            "intent": intent,
            "context": [{"cases": cases}],
            "sources": [],
            "actions": [{"type": tool_name, "detail": detail}],
        }

    if intent == "follow_up":
        ids = [p["id"] for p in payloads if "id" in p]
        if not ids:
            answer = "I couldn't register the follow-up: the tool returned no confirmation."
            detail = "no confirmation"
        else:
            answer = f"Follow-up registered with id {ids[0]}."
            detail = f"registered id {ids[0]}"
        return {
            "messages": [AIMessage(content=answer)],
            "intent": intent,
            "context": [{"follow_up_id": ids[0] if ids else None}],
            "sources": [],
            "actions": [{"type": tool_name, "detail": detail}],
        }

    if intent == "notify":
        statuses = [p.get("status") for p in payloads if "status" in p]
        status = statuses[0] if statuses else "unknown"
        if status == "stub":
            answer = "Notification skipped: no Telegram bot token is configured (stub mode)."
            detail = "stub"
        elif status == "sent":
            answer = "The notification was sent successfully."
            detail = "sent"
        else:
            answer = f"Notification status: {status}."
            detail = str(status)
        return {
            "messages": [AIMessage(content=answer)],
            "intent": intent,
            "context": [{"status": status}],
            "sources": [],
            "actions": [{"type": tool_name, "detail": detail}],
        }

    # Unknown payload shape — fall back to a graceful generic answer.
    return {
        "messages": [AIMessage(content="I received the tool result but couldn't summarize it.")],
        "intent": intent,
        "context": payloads,
        "sources": [],
        "actions": [{"type": tool_name, "detail": "unrecognized payload"}],
    }


def build_agent(
    llm: BaseChatModel | None = None,
    store: VectorStore | None = None,
    docs_dir: Path | None = None,
    db=None,
    http_client=None,
    bot_token: str | None = None,
    chat_id: str | None = None,
):
    """Build the compiled agent graph.

    llm defaults to build_llm() (gemini/openai/fake via env), store defaults
    to ./data/chroma with the configured embedder. Tests inject a FakeLLM and
    a tmp Chroma store; db / http_client / bot_token / chat_id pass through to
    build_tools so SQL and Telegram seams stay injectable at graph level too.
    """
    llm = llm or build_llm()
    store = store or VectorStore(path="./data/chroma", embedder=build_embedder())
    tools = build_tools(
        store,
        docs_dir=docs_dir,
        db=db,
        http_client=http_client,
        bot_token=bot_token,
        chat_id=chat_id,
    )

    def classify_intent(state: AgentState) -> dict:
        system_message = SystemMessage(content=LEXBOT_SYSTEM_PROMPT)
        messages = [system_message, *state["messages"]]
        response = llm.bind_tools(tools).invoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        return "tools" if _tool_call_names(state) else "compose_answer"

    def compose_answer(state: AgentState) -> dict:
        tool_names = _tool_call_names(state)

        # No tool called: check if the LLM provided a direct conversational response
        if not tool_names:
            last_ai = _last_aimessage(state)
            raw_content = last_ai.content if last_ai else ""
            content_str = raw_content if isinstance(raw_content, str) else str(raw_content)
            if content_str.strip():
                return {
                    "messages": [AIMessage(content=content_str)],
                    "intent": "conversational",
                    "context": [],
                    "sources": [],
                    "actions": [],
                }
            return {
                "messages": [AIMessage(content=OUT_OF_SCOPE_ANSWER)],
                "intent": "out_of_scope",
                "context": [],
                "sources": [],
                "actions": [],
            }

        tool_name = tool_names[0]
        intent = _INTENT_BY_TOOL.get(tool_name, tool_name)

        # Knowledge intent: cite sources on retrieval; deterministic decline +
        # notify offer on empty retrieval (AGENT-2). Other intents summarize
        # their tool's JSON payload deterministically (case/follow_up/notify).
        if intent == "knowledge":
            results = _collect_results(state)

            # Empty retrieval (AGENT-2): state the information is unavailable
            # and offer to notify a human — deterministic, not left to the LLM.
            if not results:
                return {
                    "messages": [AIMessage(content=EMPTY_RETRIEVAL_ANSWER)],
                    "intent": intent,
                    "context": [],
                    "sources": [],
                    "actions": [{"type": "notify_telegram", "detail": "offer to notify a human"}],
                }

            # Success path: compose the answer from the retrieved chunks, citing
            # sources (design data flow: compose_answer invokes the LLM with the
            # tool messages + context). The user's original question must be in
            # the prompt — without it the model answers "you haven't included a
            # question" (regression covered by test_compose_prompt_includes_user_question).
            user_text = next(
                (
                    m.content
                    for m in state["messages"]
                    if isinstance(m, HumanMessage)
                ),
                "",
            )
            sources = [
                {"id": r["id"], "text": r["text"], "source": r["source"], "distance": r["distance"]}
                for r in results
            ]
            context = "\n\n".join(f"[{r['source']}] {r['text']}" for r in results)
            prompt = (
                "You are LexBot, a warm, professional, and empathetic legal assistant for a law firm.\n"
                "Answer the user's question clearly, helpfully, and conversationally in the user's language using ONLY the retrieved knowledge below.\n"
                "Cite each source you use with its [source] tag.\n"
                "Maintain a reassuring and approachable tone for the client.\n\n"
                f"User question: {user_text}\n\n"
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

        # Non-knowledge intent: deterministic composition from the tool JSON.
        return _compose_from_tool_payload(tool_name, intent, _tool_payloads(state))

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