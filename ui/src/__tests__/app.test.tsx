import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../App";

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
  // ChatView mounts useHealth → GET /health on mount; stub so the test never
  // touches the real network (UI-5).
  fetchMock.mockResolvedValue(jsonResponse({ status: "ok", vector_count: 7, db: "ok" }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("renders the chat view with a message input", () => {
    render(<App />);
    expect(screen.getByLabelText(/message/i)).toBeInTheDocument();
  });
});