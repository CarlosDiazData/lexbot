import type { ChatMessage } from "../hooks/useChat";
import MessageBubble from "./MessageBubble";

interface ChatWindowProps {
  messages: ChatMessage[];
}

// UI-6: with no messages the window shows an empty-state prompt; the first
// message replaces it (the prompt branch is not rendered once messages exist).
export default function ChatWindow({ messages }: ChatWindowProps) {
  if (messages.length === 0) {
    return (
      <div
        data-testid="empty-state"
        className="flex flex-1 items-center justify-center text-slate-400"
      >
        <p className="text-sm">Ask LexBot anything — responses appear here.</p>
      </div>
    );
  }

  return (
    <div role="log" aria-live="polite" className="flex-1 space-y-3 overflow-y-auto">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
    </div>
  );
}