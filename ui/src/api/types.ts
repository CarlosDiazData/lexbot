// Typed contracts for the LexBot API — mirror api/src/lexbot_api/schemas.py 1:1 (design D7).

export interface ChatRequest {
  message: string;
}

export interface Source {
  id: string;
  text: string;
  source: string;
  distance: number;
  url?: string;
}

export interface Action {
  type: string;
  detail: string;
}

export interface ChatResponse {
  answer: string;
  sources: Source[];
  actions: Action[];
}

export interface HealthResponse {
  status: string;
  vector_count: number;
  db: string;
}

export interface ErrorDetail {
  code: string;
  message: string;
  retryable: boolean;
}

export interface ErrorEnvelope {
  error: ErrorDetail;
}

/**
 * Typed error for non-2xx API responses. `retryable` passes through the error
 * envelope's flag so callers can decide whether retrying is safe.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly status: number;

  constructor(code: string, message: string, retryable: boolean, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.retryable = retryable;
    this.status = status;
  }
}