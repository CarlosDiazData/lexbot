import { useEffect, useRef } from "react";
import { BookOpen, Clock, FileText, Scale, Sparkles } from "lucide-react";
import type { ChatError, ChatMessage } from "../hooks/useChat";
import ErrorBubble from "./ErrorBubble";
import MessageBubble from "./MessageBubble";

interface ChatWindowProps {
  messages: ChatMessage[];
  error: ChatError | null;
  pending?: boolean;
  onRetry: () => void;
  onSelectPrompt?: (prompt: string) => void;
}

const STARTER_PROMPTS = [
  {
    icon: FileText,
    title: "First Consultation",
    desc: "What documents should I bring to the first consultation?",
    prompt: "What documents should I bring to the first consultation?",
  },
  {
    icon: Clock,
    title: "Contract Turnaround",
    desc: "How long does a standard contract review take?",
    prompt: "How long does a standard contract review take and what are the fees?",
  },
  {
    icon: BookOpen,
    title: "Firm Policies",
    desc: "What is the policy on retainer fees and billing?",
    prompt: "What is the firm policy regarding retainer fees and confidentiality?",
  },
  {
    icon: Scale,
    title: "Case Law Research",
    desc: "Search for active cases related to corporate contracts.",
    prompt: "What legal services and consultation options are available?",
  },
];

// UI-6: with no messages the window shows an empty-state prompt; the first
// message replaces it (the prompt branch is not rendered once messages exist).
// UI-3/UI-4: a stored error renders an error bubble after the message list.
export default function ChatWindow({
  messages,
  error,
  pending = false,
  onRetry,
  onSelectPrompt,
}: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, pending, error]);

  if (messages.length === 0 && error === null) {
    return (
      <div
        data-testid="empty-state"
        className="flex flex-1 flex-col items-center justify-center px-4 py-8 text-center"
      >
        <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-600 text-white shadow-lg">
          <Sparkles className="h-7 w-7" />
        </div>

        <h2 className="mb-2 text-2xl font-bold tracking-tight text-slate-800 sm:text-3xl">
          Where would you like to start?
        </h2>
        <p className="mb-8 max-w-md text-sm text-slate-500">
          Ask LexBot anything — responses appear here. Explore firm policies, client FAQs, contract terms, or consultation details.
        </p>

        <div className="grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2 text-left">
          {STARTER_PROMPTS.map((item, index) => {
            const Icon = item.icon;
            return (
              <button
                key={index}
                type="button"
                onClick={() => onSelectPrompt?.(item.prompt)}
                className="group flex items-start gap-3 rounded-xl border border-slate-200/80 bg-white p-3.5 text-left shadow-2xs transition-all hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-xs cursor-pointer"
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 transition-colors group-hover:bg-blue-600 group-hover:text-white">
                  <Icon className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <span className="block text-xs font-semibold text-slate-800 group-hover:text-blue-600">
                    {item.title}
                  </span>
                  <span className="block text-xs text-slate-500 line-clamp-2">
                    {item.desc}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div
      role="log"
      aria-live="polite"
      className="flex-1 space-y-2 overflow-y-auto px-4 py-4"
    >
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}

      {pending && (
        <div className="my-4 flex items-start gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-tr from-blue-600 to-indigo-600 text-white shadow-xs animate-pulse">
            <Sparkles className="h-4 w-4" />
          </div>
          <div className="rounded-xl border border-slate-100 bg-slate-50/80 px-4 py-3 text-sm text-slate-500 shadow-2xs">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-blue-500 animate-bounce" />
              <span className="inline-block h-2 w-2 rounded-full bg-blue-500 animate-bounce [animation-delay:0.2s]" />
              <span className="inline-block h-2 w-2 rounded-full bg-blue-500 animate-bounce [animation-delay:0.4s]" />
              <span className="ml-1 text-xs font-medium text-slate-400">LexBot is thinking…</span>
            </div>
          </div>
        </div>
      )}

      {error !== null && <ErrorBubble error={error} onRetry={onRetry} />}
      <div ref={bottomRef} />
    </div>
  );
}