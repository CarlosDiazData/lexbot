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

  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={
          isUser
            ? "max-w-[75%] rounded-lg bg-blue-600 px-3 py-2 text-sm text-white"
            : "max-w-[75%] rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-700"
        }
      >
        <p>{linkifyAnswer(message.text, sources)}</p>

        {!isUser && sources.length > 0 && (
          <div data-testid="sources-section" className="mt-2 border-t border-slate-200 pt-2">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Sources</p>
            <div className="space-y-2">
              {sources.map((source) => (
                <SourceCard key={source.id} source={source} />
              ))}
            </div>
          </div>
        )}

        {!isUser && actions.length > 0 && (
          <div data-testid="actions-section" className="mt-2 border-t border-slate-200 pt-2">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Actions</p>
            <div className="flex flex-wrap gap-1">
              {actions.map((action, index) => (
                <ActionBadge key={`${action.type}-${index}`} action={action} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}