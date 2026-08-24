"""POST /chat — run the agent and return {answer, sources, actions} (API-1).

The agent's final state carries the ChatResponse shape: the answer is the
last AIMessage's content, sources are cited {id, text, source, distance}
records, actions are {type, detail} side-effect/offer records (AGENT-2).

Any exception from agent.ainvoke is treated as an LLM/agent failure and
re-raised as LLMUnavailableError so the global handler returns HTTP 503 with
a retry hint (API-1 "LLM failure returns 503").
"""

from fastapi import APIRouter, Depends, Request

from langchain_core.messages import HumanMessage

from ..app import LLMUnavailableError, get_agent
from ..schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request, agent=Depends(get_agent)):
    try:
        result = await agent.ainvoke({"messages": [HumanMessage(content=body.message)]})
    except Exception as exc:
        raise LLMUnavailableError(f"Agent/LLM call failed: {exc}") from exc

    final_message = result["messages"][-1]
    answer = final_message.content if isinstance(final_message.content, str) else str(final_message.content)
    return {
        "answer": answer,
        "sources": result.get("sources", []),
        "actions": result.get("actions", []),
    }