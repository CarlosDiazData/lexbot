import { useState, type FormEvent } from "react";
import { ArrowUp } from "lucide-react";

interface MessageInputProps {
  disabled: boolean;
  onSend: (message: string) => void;
}

export default function MessageInput({ disabled, onSend }: MessageInputProps) {
  const [value, setValue] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (trimmed === "" || disabled) {
      return;
    }
    onSend(trimmed);
    setValue("");
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="relative flex items-center rounded-2xl border border-slate-200 bg-white p-1.5 shadow-sm transition-all focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100"
    >
      <input
        aria-label="Message"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        disabled={disabled}
        placeholder="Ask LexBot a legal question or search policies…"
        className="flex-1 bg-transparent px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none disabled:bg-transparent disabled:text-slate-400"
      />
      <button
        type="submit"
        disabled={disabled || value.trim() === ""}
        aria-label="Send"
        className="flex h-9 items-center justify-center gap-1.5 rounded-xl bg-slate-900 px-3.5 text-xs font-semibold text-white shadow-2xs transition-all hover:bg-slate-800 active:scale-95 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400 disabled:opacity-70 cursor-pointer"
      >
        <span className="hidden sm:inline">Send</span>
        <ArrowUp className="h-4 w-4" />
      </button>
    </form>
  );
}