import { useState } from "react";
import { Check, Copy, Sparkles, User } from "lucide-react";
import type { ChatMessage } from "../hooks/useChat";
import { linkifyAnswer } from "../lib/answerLinks";
import ActionBadge from "./ActionBadge";
import SourceCard from "./SourceCard";

interface MessageBubbleProps {
  message: ChatMessage;
}

// UI-2: assistant messages render Sources and Actions sections ONLY when the
// arrays are non-empty; empty sources/actions render no section.
export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const sources = message.sources ?? [];
  const actions = message.actions ?? [];
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(message.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore clipboard write failures
    }
  }

  if (isUser) {
    return (
      <div className="flex justify-end my-3">
        <div className="flex items-start gap-2.5 max-w-[80%]">
          <div className="rounded-2xl rounded-tr-xs bg-slate-900 px-4 py-2.5 text-sm text-white shadow-xs dark:bg-blue-600">
            <p className="whitespace-pre-wrap leading-relaxed">{message.text}</p>
          </div>
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            <User className="h-4 w-4" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="group my-4 flex items-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-tr from-blue-600 to-indigo-600 text-white shadow-xs">
        <Sparkles className="h-4 w-4" />
      </div>

      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">LexBot</span>
          <button
            type="button"
            onClick={handleCopy}
            title="Copy response"
            className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-400 opacity-0 transition-opacity hover:bg-slate-100 hover:text-slate-600 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 group-hover:opacity-100 cursor-pointer"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />
                <span className="text-emerald-600 dark:text-emerald-400">Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>

        <div className="rounded-xl border border-slate-100 bg-slate-50/80 p-4 text-sm text-slate-800 shadow-2xs dark:border-slate-800/80 dark:bg-slate-900/80 dark:text-slate-200">
          <div className="whitespace-pre-wrap leading-relaxed space-y-2">
            <p>{linkifyAnswer(message.text, sources)}</p>
          </div>

          {sources.length > 0 && (
            <div
              data-testid="sources-section"
              className="mt-4 border-t border-slate-200/80 pt-3 dark:border-slate-800"
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Sources ({sources.length})
                </span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {sources.map((source) => (
                  <SourceCard key={source.id} source={source} />
                ))}
              </div>
            </div>
          )}

          {actions.length > 0 && (
            <div
              data-testid="actions-section"
              className="mt-3 border-t border-slate-200/80 pt-3 dark:border-slate-800"
            >
              <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Actions
              </span>
              <div className="flex flex-wrap gap-1.5">
                {actions.map((action, index) => (
                  <ActionBadge key={`${action.type}-${index}`} action={action} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}