import { useChat } from "../hooks/useChat";
import { useHealth } from "../hooks/useHealth";
import ChatWindow from "./ChatWindow";
import HealthIndicator from "./HealthIndicator";
import MessageInput from "./MessageInput";

// Container wiring the useChat reducer to the chat components (design D6).
// UI-1: input is disabled while a request is pending to block duplicate submits.
// UI-3: the retry callback re-sends the failed message when an error is shown.
// UI-5: the header shows the API health indicator (GET /health on mount).
export default function ChatView() {
  const { messages, phase, error, sendMessage, retry } = useChat();
  const { status } = useHealth();
  const pending = phase === "sending";

  return (
    <div className="mx-auto flex h-[80vh] max-w-2xl flex-col gap-4 rounded-lg border border-slate-200 bg-white p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-800">LexBot</h1>
        <HealthIndicator status={status} />
      </header>
      <ChatWindow messages={messages} error={error} onRetry={retry} />
      <MessageInput disabled={pending} onSend={sendMessage} />
    </div>
  );
}