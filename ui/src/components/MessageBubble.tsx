import type { ChatMessage } from "../hooks/useChat";

interface MessageBubbleProps {
  message: ChatMessage;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={
          isUser
            ? "max-w-[75%] rounded-lg bg-blue-600 px-3 py-2 text-sm text-white"
            : "max-w-[75%] rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-700"
        }
      >
        {message.text}
      </div>
    </div>
  );
}