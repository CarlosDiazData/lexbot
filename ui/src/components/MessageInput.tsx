import { useState, type FormEvent } from "react";

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
    <form onSubmit={handleSubmit} className="flex gap-2">
      <input
        aria-label="Message"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        disabled={disabled}
        placeholder="Ask LexBot…"
        className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-slate-100"
      />
      <button
        type="submit"
        disabled={disabled}
        className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        Send
      </button>
    </form>
  );
}