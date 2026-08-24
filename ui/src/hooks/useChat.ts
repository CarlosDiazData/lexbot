// Chat state via useReducer (design D6) — send/success/error/retry transitions
// are unit-testable without external state libraries.
//
// UI-1: whitespace-only input is rejected (no dispatch, no bubble); while a
// request is pending (`phase: "sending"`) further send actions are ignored so
// duplicate submits cannot fire a second request.
// UI-2: the assistant message carries the response's sources/actions so the
// bubble can render citation cards and action badges when non-empty.
// UI-3/UI-4: errors carry a retryable flag; retry re-sends the failed message
// (the failed user bubble stays — no duplicate) and clears the error.

import { useCallback, useReducer } from "react";
import { chat } from "../api/client";
import { ApiError } from "../api/types";
import type { Action, Source } from "../api/types";

export type ChatPhase = "idle" | "sending";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  sources?: Source[];
  actions?: Action[];
}

export interface ChatError {
  message: string;
  retryable: boolean;
}

export interface ChatState {
  messages: ChatMessage[];
  phase: ChatPhase;
  error: ChatError | null;
}

export type ChatAction =
  | { type: "send"; message: string; id: string }
  | { type: "success"; answer: string; id: string; sources: Source[]; actions: Action[] }
  | { type: "error"; error: ChatError }
  | { type: "retry" };

export const initialChatState: ChatState = { messages: [], phase: "idle", error: null };

let nextId = 0;
function newMessageId(): string {
  nextId += 1;
  return `msg-${nextId}`;
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "send": {
      const trimmed = action.message.trim();
      if (trimmed === "" || state.phase === "sending") {
        return state;
      }
      const userMessage: ChatMessage = { id: action.id, role: "user", text: trimmed };
      return { messages: [...state.messages, userMessage], phase: "sending", error: null };
    }
    case "success": {
      if (state.phase !== "sending") {
        return state;
      }
      const assistantMessage: ChatMessage = {
        id: action.id,
        role: "assistant",
        text: action.answer,
        sources: action.sources,
        actions: action.actions,
      };
      return { messages: [...state.messages, assistantMessage], phase: "idle", error: null };
    }
    case "error": {
      if (state.phase !== "sending") {
        return state;
      }
      return { ...state, phase: "idle", error: action.error };
    }
    case "retry": {
      // UI-3: re-send the failed message without adding a new user bubble —
      // the failed user message stays in the list.
      if (state.phase !== "idle" || state.error === null) {
        return state;
      }
      return { ...state, phase: "sending", error: null };
    }
    default:
      return state;
  }
}

function toChatError(error: unknown): ChatError {
  if (error instanceof ApiError) {
    return { message: error.message, retryable: error.retryable };
  }
  return { message: error instanceof Error ? error.message : String(error), retryable: false };
}

export function useChat() {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);

  const sendMessage = useCallback(
    async (raw: string) => {
      const trimmed = raw.trim();
      if (trimmed === "" || state.phase === "sending") {
        return;
      }
      dispatch({ type: "send", message: trimmed, id: newMessageId() });
      try {
        const response = await chat(trimmed);
        dispatch({
          type: "success",
          answer: response.answer,
          id: newMessageId(),
          sources: response.sources,
          actions: response.actions,
        });
      } catch (error) {
        dispatch({ type: "error", error: toChatError(error) });
      }
    },
    [state.phase],
  );

  const retry = useCallback(async () => {
    const failed = state.messages[state.messages.length - 1];
    if (state.phase !== "idle" || state.error === null || failed?.role !== "user") {
      return;
    }
    dispatch({ type: "retry" });
    try {
      const response = await chat(failed.text);
      dispatch({
        type: "success",
        answer: response.answer,
        id: newMessageId(),
        sources: response.sources,
        actions: response.actions,
      });
    } catch (error) {
      dispatch({ type: "error", error: toChatError(error) });
    }
  }, [state.messages, state.phase, state.error]);

  return { messages: state.messages, phase: state.phase, error: state.error, sendMessage, retry };
}