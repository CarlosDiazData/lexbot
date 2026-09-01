import { useEffect } from "react";
import { Cpu, Database, Moon, Monitor, Sun, X, Zap } from "lucide-react";
import type { Theme } from "../hooks/useTheme";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
}

const THEME_OPTIONS: { id: Theme; label: string; icon: typeof Sun }[] = [
  { id: "light", label: "Light", icon: Sun },
  { id: "dark", label: "Dark", icon: Moon },
  { id: "system", label: "System", icon: Monitor },
];

export default function SettingsModal({
  isOpen,
  onClose,
  theme,
  onThemeChange,
}: SettingsModalProps) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && isOpen) {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
      data-testid="settings-modal"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      {/* Backdrop */}
      <div
        data-testid="settings-backdrop"
        onClick={onClose}
        className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs transition-opacity animate-in fade-in duration-200"
      />

      {/* Dialog Box */}
      <div className="relative w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl transition-all dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100 animate-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between border-b border-slate-100 pb-4 dark:border-slate-800">
          <h2 id="settings-title" className="text-lg font-bold tracking-tight text-slate-800 dark:text-slate-100">
            Settings
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200 cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-6 pt-4">
          {/* Appearance Section */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
              Appearance
            </label>
            <div className="grid grid-cols-3 gap-2">
              {THEME_OPTIONS.map((option) => {
                const Icon = option.icon;
                const active = theme === option.id;
                return (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => onThemeChange(option.id)}
                    data-testid={`theme-option-${option.id}`}
                    className={`flex flex-col items-center gap-2 rounded-xl border p-3 text-xs font-medium transition-all cursor-pointer ${
                      active
                        ? "border-blue-600 bg-blue-50/70 text-blue-700 shadow-2xs dark:border-blue-500 dark:bg-blue-950/40 dark:text-blue-400"
                        : "border-slate-200/80 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-800/60 dark:text-slate-400 dark:hover:bg-slate-800"
                    }`}
                  >
                    <Icon className={`h-5 w-5 ${active ? "text-blue-600 dark:text-blue-400" : ""}`} />
                    <span>{option.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* System & Architecture Info */}
          <div className="border-t border-slate-100 pt-4 dark:border-slate-800">
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
              System & Engine
            </label>
            <div className="space-y-2 rounded-xl border border-slate-100 bg-slate-50/70 p-3.5 text-xs dark:border-slate-800/80 dark:bg-slate-950/40">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-slate-600 dark:text-slate-400">
                  <Cpu className="h-3.5 w-3.5 text-blue-500" />
                  <span>LLM Model</span>
                </div>
                <span className="font-semibold text-slate-800 dark:text-slate-200">
                  gemini-2.5-flash-lite
                </span>
              </div>

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-slate-600 dark:text-slate-400">
                  <Database className="h-3.5 w-3.5 text-emerald-500" />
                  <span>Vector Database</span>
                </div>
                <span className="font-semibold text-slate-800 dark:text-slate-200">
                  pgvector (AWS Aurora)
                </span>
              </div>

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-slate-600 dark:text-slate-400">
                  <Zap className="h-3.5 w-3.5 text-amber-500" />
                  <span>Architecture</span>
                </div>
                <span className="font-semibold text-slate-800 dark:text-slate-200">
                  LangGraph Agentic RAG
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="mt-6 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl bg-slate-900 px-4 py-2 text-xs font-semibold text-white shadow-2xs hover:bg-slate-800 active:scale-95 dark:bg-slate-800 dark:hover:bg-slate-700 cursor-pointer"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
