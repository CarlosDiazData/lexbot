"""Pydantic request/response schemas for the LexBot API (design interfaces).

ChatResponse mirrors the agent's ChatResponse shape: {answer, sources, actions}
where sources are cited {id, text, source, distance} and actions are
{type, detail} side-effect/offer records. ErrorEnvelope is the single error
shape produced by the global exception handler:
{"error": {"code", "message", "retryable"}}.
"""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class Source(BaseModel):
    id: str
    text: str
    source: str
    distance: float


class Action(BaseModel):
    type: str
    detail: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    actions: list[Action]


class IngestResponse(BaseModel):
    documents: int
    chunks: int


class HealthResponse(BaseModel):
    status: str
    vector_count: int
    db: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool


class ErrorEnvelope(BaseModel):
    error: ErrorDetail