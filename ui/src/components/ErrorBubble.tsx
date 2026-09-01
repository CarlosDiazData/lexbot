import { AlertCircle, RotateCcw } from "lucide-react";
import type { ChatError } from "../hooks/useChat";

interface ErrorBubbleProps {
  error: ChatError;
  onRetry: () => void;
}

// UI-3/UI-4: retryable errors show the message plus a Retry control; non-retryable
// errors show only the message (no control).
export default function ErrorBubble({ error, onRetry }: ErrorBubbleProps) {
  return (
    <div data-testid="error-bubble" role="alert" className="my-3 flex justify-start">
      <div className="flex max-w-[85%] items-start gap-3 rounded-xl border border-red-200 bg-red-50/90 p-3.5 text-sm text-red-800 shadow-2xs">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
        <div className="flex-1 space-y-2">
          <p className="leading-relaxed">{error.message}</p>
          {error.retryable && (
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white shadow-2xs transition-colors hover:bg-red-700 active:scale-95 cursor-pointer"
            >
              <RotateCcw className="h-3 w-3" />
              Retry
            </button>
          )}
        </div>
      </div>
    </div>
  );
}