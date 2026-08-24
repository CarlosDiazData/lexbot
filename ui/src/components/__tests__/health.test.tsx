import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import ChatView from "../ChatView";

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

describe("HealthIndicator", () => {
  it("shows connected when /health returns 200 ok (UI-5.1)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "ok", vector_count: 7, db: "ok" }));
    render(<ChatView />);

    expect(await screen.findByText("connected")).toBeInTheDocument();
    expect(screen.getByTestId("health-indicator")).toHaveAttribute("data-status", "ok");
  });

  it("shows degraded when the health check fails (UI-5.1)", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<ChatView />);

    expect(await screen.findByText("degraded")).toBeInTheDocument();
    expect(screen.getByTestId("health-indicator")).toHaveAttribute("data-status", "degraded");
  });
});