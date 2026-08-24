// Chat state via useReducer (design D6) — send/success/error transitions are
// unit-testable without external state libraries.
//
// UI-1: whitespace-only input is rejected (no dispatch, no bubble); while a
// request is pending (`phase: "sending"`) further send actions are ignored so
// duplicate submits cannot fire a second request.

import { useCallback, useReducer } from "react";
import { chat } from "../api/client";

export type ChatPhase = "idle" | "sending";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
}

export interface ChatState {
  messages: ChatMessage[];
  phase: ChatPhase;
  error: string | null;
}

export type ChatAction =
  | { type: "send"; message: string; id: string }
  | { type: "success"; answer: string; id: string }
  | { type: "error"; error: string };

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
      const assistantMessage: ChatMessage = { id: action.id, role: "assistant", text: action.answer };
      return { messages: [...state.messages, assistantMessage], phase: "idle", error: null };
    }
    case "error": {
      if (state.phase !== "sending") {
        return state;
      }
      return { ...state, phase: "idle", error: action.error };
    }
    default:
      return state;
  }
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
        dispatch({ type: "success", answer: response.answer, id: newMessageId() });
      } catch (error) {
        dispatch({ type: "error", error: error instanceof Error ? error.message : String(error) });
      }
    },
    [state.phase],
  );

  return { messages: state.messages, phase: state.phase, error: state.error, sendMessage };
}