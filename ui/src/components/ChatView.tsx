import { useState } from "react";
import { Settings, Sparkles } from "lucide-react";
import { useChat } from "../hooks/useChat";
import { useHealth } from "../hooks/useHealth";
import { useTheme } from "../hooks/useTheme";
import ChatWindow from "./ChatWindow";
import HealthIndicator from "./HealthIndicator";
import MessageInput from "./MessageInput";
import SettingsModal from "./SettingsModal";

// Container wiring the useChat reducer to the chat components (design D6).
// UI-1: input is disabled while a request is pending to block duplicate submits.
// UI-3: the retry callback re-sends the failed message when an error is shown.
// UI-5: the header shows the API health indicator (GET /health on mount).
export default function ChatView() {
  const { messages, phase, error, sendMessage, retry } = useChat();
  const { status } = useHealth();
  const { theme, setTheme } = useTheme();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const pending = phase === "sending";

  return (
    <div className="flex h-screen w-full flex-col bg-slate-50 text-slate-900 transition-colors dark:bg-slate-950 dark:text-slate-100">
      {/* Top Navigation Bar */}
      <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center justify-between border-b border-slate-200/80 bg-white/80 px-4 backdrop-blur-md dark:border-slate-800 dark:bg-slate-900/80 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-tr from-blue-600 to-indigo-600 text-white shadow-2xs">
            <Sparkles className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-bold tracking-tight text-slate-800 dark:text-slate-100">LexBot</h1>
              <span className="hidden rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700 border border-blue-200/60 dark:bg-blue-950/50 dark:text-blue-300 dark:border-blue-800/60 sm:inline-block">
                Legal AI Assistant
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <HealthIndicator status={status} />
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            aria-label="Open settings"
            title="Settings"
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200/80 bg-white text-slate-600 shadow-2xs transition-colors hover:bg-slate-100 hover:text-slate-900 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 cursor-pointer"
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>
      </header>

      {/* Main Conversation Stream */}
      <main className="mx-auto flex flex-1 w-full max-w-3xl flex-col overflow-hidden">
        <ChatWindow
          messages={messages}
          error={error}
          pending={pending}
          onRetry={retry}
          onSelectPrompt={sendMessage}
        />

        {/* Floating Input Area */}
        <div className="shrink-0 p-4 pt-0">
          <MessageInput disabled={pending} onSend={sendMessage} />
          <p className="mt-2 text-center text-[11px] text-slate-400 dark:text-slate-500">
            LexBot is an AI assistant providing legal information from firm documents, not formal legal advice.
          </p>
        </div>
      </main>

      {/* Settings Modal */}
      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        theme={theme}
        onThemeChange={setTheme}
      />
    </div>
  );
}