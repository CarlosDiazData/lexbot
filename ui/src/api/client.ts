// Minimal fetch wrapper for the LexBot API (design D7). `fetch` is the sole
// network boundary; every unit/component test mocks it.
//
// Base URL comes from VITE_API_URL, defaulting to http://localhost:8000
// (CLIENT-2). Non-2xx responses are parsed from the error envelope
// {error: {code, message, retryable}} into an ApiError (CLIENT-1).

import type { ChatRequest, ChatResponse, ErrorEnvelope, HealthResponse } from "./types";
import { ApiError } from "./types";

const DEFAULT_BASE_URL = "http://localhost:8000";
const RETRY_DELAY_MS = 500;
const MAX_RETRIES = 1;

function getBaseUrl(): string {
  const configured = import.meta.env.VITE_API_URL;
  if (typeof configured === "string" && configured.trim() !== "") {
    return configured.trim();
  }
  return import.meta.env.DEV ? DEFAULT_BASE_URL : "";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${getBaseUrl()}${path}`, {
    method: init.method ?? "GET",
    headers: { "Content-Type": "application/json" },
    body: init.body,
    signal: init.signal,
  });

  if (!response.ok) {
    throw await toApiError(response);
  }

  return (await response.json()) as T;
}

async function toApiError(response: Response): Promise<ApiError> {
  let detail: ErrorEnvelope["error"] | null = null;
  try {
    const envelope = (await response.json()) as ErrorEnvelope;
    if (envelope?.error && typeof envelope.error.code === "string") {
      detail = envelope.error;
    }
  } catch {
    // Non-JSON error body — fall back to HTTP status fields.
  }

  return new ApiError(
    detail?.code ?? `http_${response.status}`,
    detail?.message ?? response.statusText,
    detail?.retryable ?? response.status >= 500,
    response.status,
  );
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** POST /chat — send a message and parse {answer, sources, actions} (CLIENT-1). */
export async function chat(message: string, signal?: AbortSignal): Promise<ChatResponse> {
  const body: ChatRequest = { message };
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await request<ChatResponse>("/chat", {
        method: "POST",
        body: JSON.stringify(body),
        signal,
      });
    } catch (error) {
      // Retry once (500ms) on retryable errors, then throw. Aborts and
      // non-retryable errors surface immediately.
      if (!(error instanceof ApiError) || !error.retryable || attempt >= MAX_RETRIES) {
        throw error;
      }
      await delay(RETRY_DELAY_MS);
    }
  }
}

/** GET /health — parse {status, vector_count, db} (CLIENT-3). */
export function health(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}