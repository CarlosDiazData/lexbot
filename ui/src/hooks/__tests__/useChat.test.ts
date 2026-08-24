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
    const next = chatReducer(sent, { type: "success", answer: "the answer", id: "m2" });
    expect(next.messages).toEqual([
      { id: "m1", role: "user", text: "hi" },
      { id: "m2", role: "assistant", text: "the answer" },
    ]);
    expect(next.phase).toBe("idle");
  });

  it("ignores send actions while a request is pending", () => {
    const sent = chatReducer(initialChatState, { type: "send", message: "hi", id: "m1" });
    const next = chatReducer(sent, { type: "send", message: "again", id: "m2" });
    expect(next).toBe(sent);
    expect(next.messages).toHaveLength(1);
  });

  it("stores the error and returns to idle on failure", () => {
    const sent = chatReducer(initialChatState, { type: "send", message: "hi", id: "m1" });
    const next = chatReducer(sent, { type: "error", error: "boom" });
    expect(next.phase).toBe("idle");
    expect(next.error).toBe("boom");
    expect(next.messages).toHaveLength(1);
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
});