import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

describe("ChatView", () => {
  it("shows the empty-state prompt on fresh load (UI-6.1)", () => {
    render(<ChatView />);
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    expect(screen.getByText(/ask lexbot anything/i)).toBeInTheDocument();
  });

  it("renders a user bubble and the answer bubble after sending (UI-1.1)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ answer: "LexBot's answer", sources: [], actions: [] }));
    const user = userEvent.setup();
    render(<ChatView />);

    await user.type(screen.getByLabelText(/message/i), "What is LexBot?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("What is LexBot?")).toBeInTheDocument();
    expect(await screen.findByText("LexBot's answer")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("replaces the empty state after the first message (UI-6.1)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ answer: "the answer", sources: [], actions: [] }));
    const user = userEvent.setup();
    render(<ChatView />);

    expect(screen.getByTestId("empty-state")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/message/i), "hi");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("the answer")).toBeInTheDocument();
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
  });

  it("disables the input and send button while a request is pending (UI-1)", async () => {
    let resolveFetch!: (value: unknown) => void;
    fetchMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );
    const user = userEvent.setup();
    render(<ChatView />);

    await user.type(screen.getByLabelText(/message/i), "hello");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(screen.getByLabelText(/message/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Resolve the pending request so the test leaves no dangling promise.
    await act(async () => {
      resolveFetch(jsonResponse({ answer: "done", sources: [], actions: [] }));
    });
  });

  it("renders source cards and action badges with all fields (UI-2.1)", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        answer: "Here is the cited answer.",
        sources: [
          { id: "doc-1", text: "RAG explanation text.", source: "docs/faq.md", distance: 0.1234 },
          { id: "doc-2", text: "Vector store detail.", source: "docs/architecture.md", distance: 0.5678 },
        ],
        actions: [
          { type: "search", detail: "knowledge base" },
          { type: "cite", detail: "doc-1" },
        ],
      }),
    );
    const user = userEvent.setup();
    render(<ChatView />);

    await user.type(screen.getByLabelText(/message/i), "how does lexbot work?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("Here is the cited answer.")).toBeInTheDocument();

    expect(screen.getByTestId("sources-section")).toBeInTheDocument();
    expect(screen.getByTestId("actions-section")).toBeInTheDocument();

    const cards = screen.getAllByTestId("source-card");
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByText("doc-1")).toBeInTheDocument();
    expect(within(cards[0]).getByText("RAG explanation text.")).toBeInTheDocument();
    expect(within(cards[0]).getByText("docs/faq.md")).toBeInTheDocument();
    expect(within(cards[0]).getByText("distance: 0.1234")).toBeInTheDocument();
    expect(within(cards[1]).getByText("doc-2")).toBeInTheDocument();
    expect(within(cards[1]).getByText("Vector store detail.")).toBeInTheDocument();
    expect(within(cards[1]).getByText("docs/architecture.md")).toBeInTheDocument();
    expect(within(cards[1]).getByText("distance: 0.5678")).toBeInTheDocument();

    const badges = screen.getAllByTestId("action-badge");
    expect(badges).toHaveLength(2);
    expect(within(badges[0]).getByText(/search: knowledge base/)).toBeInTheDocument();
    expect(within(badges[1]).getByText(/cite: doc-1/)).toBeInTheDocument();
  });

  it("hides sources and actions sections when both are empty (UI-2.2)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ answer: "plain answer", sources: [], actions: [] }));
    const user = userEvent.setup();
    render(<ChatView />);

    await user.type(screen.getByLabelText(/message/i), "hi");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("plain answer")).toBeInTheDocument();
    expect(screen.queryByTestId("sources-section")).not.toBeInTheDocument();
    expect(screen.queryByTestId("actions-section")).not.toBeInTheDocument();
    expect(screen.queryAllByTestId("source-card")).toHaveLength(0);
    expect(screen.queryAllByTestId("action-badge")).toHaveLength(0);
  });

  it("shows an error bubble with Retry on 503 and retry renders the answer (UI-3.1)", async () => {
    vi.useFakeTimers();
    try {
      // Client auto-retries once (500ms) on retryable, then throws — the error
      // bubble appears after both attempts fail.
      fetchMock
        .mockResolvedValueOnce(
          jsonResponse({ error: { code: "llm_unavailable", message: "LLM unavailable, retry later", retryable: true } }, 503),
        )
        .mockResolvedValueOnce(
          jsonResponse({ error: { code: "llm_unavailable", message: "LLM unavailable, retry later", retryable: true } }, 503),
        )
        .mockResolvedValueOnce(jsonResponse({ answer: "recovered answer", sources: [], actions: [] }, 200));

      // fireEvent (not userEvent) so no internal timers interfere with fake timers.
      render(<ChatView />);
      fireEvent.change(screen.getByLabelText(/message/i), { target: { value: "hello" } });
      fireEvent.click(screen.getByRole("button", { name: /send/i }));

      // Flush the client's 500ms auto-retry so the ApiError reaches the reducer.
      // The hook's try/catch owns the rejection, so advancing timers is safe
      // (obs 685: attach rejection handling before advancing).
      await act(async () => {
        await vi.advanceTimersByTimeAsync(500);
      });

      expect(screen.getByText("LLM unavailable, retry later")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /retry/i }));

      // The 200 response resolves via microtasks (no timer), so flush and assert.
      await act(async () => {});
      expect(screen.getByText("recovered answer")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows the error message without a retry control on 500 (UI-4.1)", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ error: { code: "internal_error", message: "Internal server error", retryable: false } }, 500),
    );
    const user = userEvent.setup();
    render(<ChatView />);

    await user.type(screen.getByLabelText(/message/i), "hello");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("Internal server error")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});