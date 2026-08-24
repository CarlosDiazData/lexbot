import type { ChatError, ChatMessage } from "../hooks/useChat";
import ErrorBubble from "./ErrorBubble";
import MessageBubble from "./MessageBubble";

interface ChatWindowProps {
  messages: ChatMessage[];
  error: ChatError | null;
  onRetry: () => void;
}

// UI-6: with no messages the window shows an empty-state prompt; the first
// message replaces it (the prompt branch is not rendered once messages exist).
// UI-3/UI-4: a stored error renders an error bubble after the message list.
export default function ChatWindow({ messages, error, onRetry }: ChatWindowProps) {
  if (messages.length === 0 && error === null) {
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
      {error !== null && <ErrorBubble error={error} onRetry={onRetry} />}
    </div>
  );
}