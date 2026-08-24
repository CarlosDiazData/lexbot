import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
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
});