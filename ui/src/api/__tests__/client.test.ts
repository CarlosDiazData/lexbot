import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chat, health } from "../client";
import { ApiError } from "../types";

const DEFAULT_BASE_URL = "http://localhost:8000";

const fetchMock = vi.fn();

function jsonResponse(payload: unknown, status = 200, statusText = "OK") {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: async () => payload,
  } as unknown as Response;
}

async function rejectionOf(promise: Promise<unknown>): Promise<unknown> {
  return promise.then(
    () => {
      throw new Error("expected promise to reject");
    },
    (error) => error,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.useRealTimers();
  delete import.meta.env.VITE_API_URL;
});

describe("chat", () => {
  it("parses answer, sources[0] and actions[0] from a 200 response", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        answer: "LexBot's answer",
        sources: [{ id: "src-1", text: "chunk text", source: "doc.pdf", distance: 0.12 }],
        actions: [{ type: "offer", detail: "download" }],
      }),
    );

    const result = await chat("hello");

    expect(result.answer).toBe("LexBot's answer");
    expect(result.sources[0]).toEqual({ id: "src-1", text: "chunk text", source: "doc.pdf", distance: 0.12 });
    expect(result.actions[0]).toEqual({ type: "offer", detail: "download" });
    expect(fetchMock).toHaveBeenCalledWith(`${DEFAULT_BASE_URL}/chat`, expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("parses a 503 retryable envelope into ApiError and retries once before throwing", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValue(
      jsonResponse(
        { error: { code: "llm_unavailable", message: "LLM temporarily unavailable", retryable: true } },
        503,
        "Service Unavailable",
      ),
    );

    const promise = chat("hello");
    const errorPromise = rejectionOf(promise); // attach handler before timers fire
    await vi.runAllTimersAsync();

    const error = await errorPromise;
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      name: "ApiError",
      code: "llm_unavailable",
      message: "LLM temporarily unavailable",
      retryable: true,
      status: 503,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2); // initial attempt + one retry, then throws
  });

  it("retries once and resolves when the second attempt succeeds", async () => {
    vi.useFakeTimers();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: "llm_unavailable", message: "busy", retryable: true } }, 503, "Service Unavailable"),
      )
      .mockResolvedValueOnce(jsonResponse({ answer: "recovered", sources: [], actions: [] }));

    const promise = chat("hello");
    await vi.runAllTimersAsync();

    await expect(promise).resolves.toEqual({ answer: "recovered", sources: [], actions: [] });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry a non-retryable 500 error", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ error: { code: "internal_error", message: "boom", retryable: false } }, 500, "Internal Server Error"),
    );

    const error = await rejectionOf(chat("hello"));
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      code: "internal_error",
      message: "boom",
      retryable: false,
      status: 500,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("base URL", () => {
  it("targets the default http://localhost:8000 when VITE_API_URL is unset in dev", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ answer: "a", sources: [], actions: [] }));

    await chat("hello");

    expect(fetchMock).toHaveBeenCalledWith(`${DEFAULT_BASE_URL}/chat`, expect.objectContaining({ method: "POST" }));
  });

  it("targets relative /chat in production when VITE_API_URL is unset", async () => {
    vi.stubEnv("DEV", false);
    fetchMock.mockResolvedValue(jsonResponse({ answer: "a", sources: [], actions: [] }));

    await chat("hello");

    expect(fetchMock).toHaveBeenCalledWith("/chat", expect.objectContaining({ method: "POST" }));
  });

  it("targets the VITE_API_URL override when set", async () => {
    import.meta.env.VITE_API_URL = "http://localhost:9999";
    fetchMock.mockResolvedValue(jsonResponse({ answer: "a", sources: [], actions: [] }));

    await chat("hello");

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:9999/chat", expect.objectContaining({ method: "POST" }));
  });
});

describe("health", () => {
  it("parses {status, vector_count, db} from a 200 response", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "ok", vector_count: 7, db: "ok" }));

    const result = await health();

    expect(result).toEqual({ status: "ok", vector_count: 7, db: "ok" });
    expect(fetchMock).toHaveBeenCalledWith(`${DEFAULT_BASE_URL}/health`, expect.objectContaining({ method: "GET" }));
  });
});