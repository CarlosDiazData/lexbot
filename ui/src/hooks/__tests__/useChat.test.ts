import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { chatReducer, initialChatState, useChat } from "../useChat";

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    json: async () => payload,
  } as unknown as Response;
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("chatReducer", () => {
  it("appends a user message and moves to sending", () => {
    const next = chatReducer(initialChatState, { type: "send", message: "hi", id: "m1" });
    expect(next.messages).toEqual([{ id: "m1", role: "user", text: "hi" }]);
    expect(next.phase).toBe("sending");
  });

  it("rejects whitespace-only send actions without changing state", () => {
    const next = chatReducer(initialChatState, { type: "send", message: "   \n\t ", id: "m1" });
    expect(next).toBe(initialChatState);
  });

  it("appends the assistant answer and returns to idle on success", () => {
    const sent = chatReducer(initialChatState, { type: "send", message: "hi", id: "m1" });
    const next = chatReducer(sent, {
      type: "success",
      answer: "the answer",
      id: "m2",
      sources: [],
      actions: [],
    });
    expect(next.messages).toEqual([
      { id: "m1", role: "user", text: "hi" },
      { id: "m2", role: "assistant", text: "the answer", sources: [], actions: [] },
    ]);
    expect(next.phase).toBe("idle");
  });

  it("stores sources and actions on the assistant message (UI-2)", () => {
    const sent = chatReducer(initialChatState, { type: "send", message: "hi", id: "m1" });
    const next = chatReducer(sent, {
      type: "success",
      answer: "answer",
      id: "m2",
      sources: [{ id: "s1", text: "t", source: "src", distance: 0.1 }],
      actions: [{ type: "search", detail: "kb" }],
    });
    expect(next.messages[1].sources).toEqual([{ id: "s1", text: "t", source: "src", distance: 0.1 }]);
    expect(next.messages[1].actions).toEqual([{ type: "search", detail: "kb" }]);
  });

  it("ignores send actions while a request is pending", () => {
    const sent = chatReducer(initialChatState, { type: "send", message: "hi", id: "m1" });
    const next = chatReducer(sent, { type: "send", message: "again", id: "m2" });
    expect(next).toBe(sent);
    expect(next.messages).toHaveLength(1);
  });

  it("stores the error and returns to idle on failure (UI-3/UI-4)", () => {
    const sent = chatReducer(initialChatState, { type: "send", message: "hi", id: "m1" });
    const next = chatReducer(sent, { type: "error", error: { message: "boom", retryable: false } });
    expect(next.phase).toBe("idle");
    expect(next.error).toEqual({ message: "boom", retryable: false });
    expect(next.messages).toHaveLength(1);
  });

  it("retry re-enters sending without duplicating the user bubble (UI-3)", () => {
    const sent = chatReducer(initialChatState, { type: "send", message: "hi", id: "m1" });
    const failed = chatReducer(sent, { type: "error", error: { message: "boom", retryable: true } });
    const next = chatReducer(failed, { type: "retry" });
    expect(next.phase).toBe("sending");
    expect(next.error).toBeNull();
    expect(next.messages).toEqual([{ id: "m1", role: "user", text: "hi" }]);
  });

  it("ignores retry when there is no error to retry", () => {
    const next = chatReducer(initialChatState, { type: "retry" });
    expect(next).toBe(initialChatState);
  });
});

describe("useChat", () => {
  it("does not dispatch or create a bubble for whitespace-only input (UI-1.2)", async () => {
    const { result } = renderHook(() => useChat());

    await act(async () => {
      result.current.sendMessage("   \n\t ");
    });

    expect(result.current.messages).toHaveLength(0);
    expect(result.current.phase).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("blocks a duplicate submit while a request is pending", async () => {
    let resolveFetch!: (value: unknown) => void;
    fetchMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );

    const { result } = renderHook(() => useChat());

    await act(async () => {
      result.current.sendMessage("hello");
    });

    expect(result.current.phase).toBe("sending");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      result.current.sendMessage("world");
    });

    expect(result.current.messages).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Resolve the pending request so the success transition is also covered.
    await act(async () => {
      resolveFetch(jsonResponse({ answer: "recovered", sources: [], actions: [] }));
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.phase).toBe("idle");
  });

  it("stores a non-retryable error without auto-retry (UI-4.1)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ error: { code: "internal_error", message: "Internal server error", retryable: false } }, 500),
    );

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(result.current.error).toEqual({ message: "Internal server error", retryable: false });
    expect(result.current.phase).toBe("idle");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retry re-sends the same message and recovers on 200 (UI-3.1)", async () => {
    vi.useFakeTimers();
    try {
      // Client auto-retries once (500ms) on retryable, then throws.
      fetchMock
        .mockResolvedValueOnce(
          jsonResponse({ error: { code: "llm_unavailable", message: "LLM unavailable, retry later", retryable: true } }, 503),
        )
        .mockResolvedValueOnce(
          jsonResponse({ error: { code: "llm_unavailable", message: "LLM unavailable, retry later", retryable: true } }, 503),
        )
        .mockResolvedValueOnce(jsonResponse({ answer: "recovered answer", sources: [], actions: [] }, 200));

      const { result } = renderHook(() => useChat());

      await act(async () => {
        const promise = result.current.sendMessage("hello");
        // Rejection is handled inside the hook's try/catch; advance timers to
        // flush the client's 500ms auto-retry (obs 685 pattern).
        await vi.advanceTimersByTimeAsync(500);
        await promise;
      });

      expect(result.current.error).toEqual({ message: "LLM unavailable, retry later", retryable: true });
      expect(result.current.phase).toBe("idle");
      expect(result.current.messages).toHaveLength(1);

      await act(async () => {
        await result.current.retry();
      });

      expect(result.current.messages).toHaveLength(2);
      expect(result.current.messages[1].text).toBe("recovered answer");
      expect(result.current.error).toBeNull();
      expect(result.current.phase).toBe("idle");
      expect(fetchMock).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });
});