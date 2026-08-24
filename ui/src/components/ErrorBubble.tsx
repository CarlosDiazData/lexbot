import type { ChatError } from "../hooks/useChat";

interface ErrorBubbleProps {
  error: ChatError;
  onRetry: () => void;
}

// UI-3/UI-4: retryable errors show the message plus a Retry control; non-retryable
// errors show only the message (no control).
export default function ErrorBubble({ error, onRetry }: ErrorBubbleProps) {
  return (
    <div data-testid="error-bubble" role="alert" className="flex justify-start">
      <div className="max-w-[75%] rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
        <p>{error.message}</p>
        {error.retryable && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 rounded bg-red-600 px-3 py-1 text-xs font-semibold text-white hover:bg-red-700"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}