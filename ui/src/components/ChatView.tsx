import { useChat } from "../hooks/useChat";
import ChatWindow from "./ChatWindow";
import MessageInput from "./MessageInput";

// Container wiring the useChat reducer to the chat components (design D6).
// UI-1: input is disabled while a request is pending to block duplicate submits.
// UI-3: the retry callback re-sends the failed message when an error is shown.
export default function ChatView() {
  const { messages, phase, error, sendMessage, retry } = useChat();
  const pending = phase === "sending";

  return (
    <div className="mx-auto flex h-[80vh] max-w-2xl flex-col gap-4 rounded-lg border border-slate-200 bg-white p-6">
      <ChatWindow messages={messages} error={error} onRetry={retry} />
      <MessageInput disabled={pending} onSend={sendMessage} />
    </div>
  );
}