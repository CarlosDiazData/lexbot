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

const HEALTH_OK = { status: "ok", vector_count: 7, db: "ok" };
const DEFAULT_ANSWER = { answer: "ok", sources: [], actions: [] };

const fetchMock = vi.fn();

// Queue of responses served to /chat calls. /health always answers 200 ok so
// the header indicator (unit 5) never interferes with chat-flow assertions.
function mockChatResponses(...responses: Response[]) {
  const queue = [...responses];
  fetchMock.mockImplementation((url: RequestInfo | URL) => {
    if (String(url).includes("/health")) {
      return Promise.resolve(jsonResponse(HEALTH_OK));
    }
    return Promise.resolve(queue.shift() ?? jsonResponse(DEFAULT_ANSWER));
  });
}

// Count only /chat calls — /health fires once on mount in every test.
function chatFetchCount(): number {
  return fetchMock.mock.calls.filter(([url]) => !String(url).includes("/health")).length;
}

beforeEach(() => {
  fetchMock.mockReset();
  mockChatResponses();
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
    mockChatResponses(jsonResponse({ answer: "LexBot's answer", sources: [], actions: [] }));
    const user = userEvent.setup();
    render(<ChatView />);

    await user.type(screen.getByLabelText(/message/i), "What is LexBot?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("What is LexBot?")).toBeInTheDocument();
    expect(await screen.findByText("LexBot's answer")).toBeInTheDocument();
    expect(chatFetchCount()).toBe(1);
  });

  it("replaces the empty state after the first message (UI-6.1)", async () => {
    mockChatResponses(jsonResponse({ answer: "the answer", sources: [], actions: [] }));
    const user = userEvent.setup();
    render(<ChatView />);

    expect(screen.getByTestId("empty-state")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/message/i), "hi");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("the answer")).toBeInTheDocument();
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
  });

  it("disables the input and send button while a request is pending (UI-1)", async () => {
    // The pending promise also serves the mount-time /health call (health
    // stays "checking" until resolved at the end) — harmless for this test.
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
    expect(chatFetchCount()).toBe(1);

    // Resolve the pending request so the test leaves no dangling promise.
    await act(async () => {
      resolveFetch(jsonResponse({ answer: "done", sources: [], actions: [] }));
    });
  });

  it("renders source cards and action badges with all fields (UI-2.1)", async () => {
    mockChatResponses(
      jsonResponse({
        answer: "Here is the cited answer.",
        sources: [
          {
            id: "doc-1",
            text: "RAG explanation text.",
            source: "docs/faq.md",
            distance: 0.1234,
            url: "https://github.com/CarlosDiazData/lexbot/blob/main/docs/knowledge/docs/faq.md",
          },
          {
            id: "doc-2",
            text: "Vector store detail.",
            source: "docs/architecture.md",
            distance: 0.5678,
            url: "https://github.com/CarlosDiazData/lexbot/blob/main/docs/knowledge/docs/architecture.md",
          },
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
    const sourceLink1 = within(cards[0]).getByRole("link", { name: "docs/faq.md" });
    expect(sourceLink1).toHaveAttribute(
      "href",
      "https://github.com/CarlosDiazData/lexbot/blob/main/docs/knowledge/docs/faq.md",
    );
    expect(sourceLink1).toHaveAttribute("target", "_blank");
    expect(sourceLink1).toHaveAttribute("rel", "noreferrer");
    expect(within(cards[0]).getByText("distance: 0.1234")).toBeInTheDocument();
    expect(within(cards[1]).getByText("doc-2")).toBeInTheDocument();
    expect(within(cards[1]).getByText("Vector store detail.")).toBeInTheDocument();
    const sourceLink2 = within(cards[1]).getByRole("link", { name: "docs/architecture.md" });
    expect(sourceLink2).toHaveAttribute(
      "href",
      "https://github.com/CarlosDiazData/lexbot/blob/main/docs/knowledge/docs/architecture.md",
    );
    expect(sourceLink2).toHaveAttribute("target", "_blank");
    expect(within(cards[1]).getByText("distance: 0.5678")).toBeInTheDocument();

    const badges = screen.getAllByTestId("action-badge");
    expect(badges).toHaveLength(2);
    expect(within(badges[0]).getByText(/search: knowledge base/)).toBeInTheDocument();
    expect(within(badges[1]).getByText(/cite: doc-1/)).toBeInTheDocument();
  });

  it("linkifies known [slug] citations in the answer and leaves unknown tags literal", async () => {
    mockChatResponses(
      jsonResponse({
        answer: "See [docs/faq.md] for the policy, but [bogus.md] is not a real citation.",
        sources: [
          {
            id: "doc-1",
            text: "RAG explanation text.",
            source: "docs/faq.md",
            distance: 0.1234,
            url: "https://github.com/CarlosDiazData/lexbot/blob/main/docs/knowledge/docs/faq.md",
          },
        ],
        actions: [],
      }),
    );
    const user = userEvent.setup();
    render(<ChatView />);

    await user.type(screen.getByLabelText(/message/i), "what is the policy?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    const citation = await screen.findByRole("link", { name: "[docs/faq.md]" });
    expect(citation).toHaveAttribute(
      "href",
      "https://github.com/CarlosDiazData/lexbot/blob/main/docs/knowledge/docs/faq.md",
    );
    expect(citation).toHaveAttribute("target", "_blank");
    expect(citation).toHaveAttribute("rel", "noreferrer");
    expect(screen.getByText(/bogus\.md.*is not a real citation/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "[bogus.md]" })).not.toBeInTheDocument();
  });

  it("hides sources and actions sections when both are empty (UI-2.2)", async () => {
    mockChatResponses(jsonResponse({ answer: "plain answer", sources: [], actions: [] }));
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
      // bubble appears after both attempts fail. The queue feeds only /chat;
      // /health answers 200 ok on mount (routed in mockChatResponses).
      mockChatResponses(
        jsonResponse({ error: { code: "llm_unavailable", message: "LLM unavailable, retry later", retryable: true } }, 503),
        jsonResponse({ error: { code: "llm_unavailable", message: "LLM unavailable, retry later", retryable: true } }, 503),
        jsonResponse({ answer: "recovered answer", sources: [], actions: [] }, 200),
      );

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
      expect(chatFetchCount()).toBe(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows the error message without a retry control on 500 (UI-4.1)", async () => {
    mockChatResponses(
      jsonResponse({ error: { code: "internal_error", message: "Internal server error", retryable: false } }, 500),
    );
    const user = userEvent.setup();
    render(<ChatView />);

    await user.type(screen.getByLabelText(/message/i), "hello");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("Internal server error")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(chatFetchCount()).toBe(1);
  });
});