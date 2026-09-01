import { Bell, Calendar, Scale, Sparkles } from "lucide-react";
import type { Action } from "../api/types";

interface ActionBadgeProps {
  action: Action;
}

function getActionIcon(type: string) {
  if (type.includes("telegram") || type.includes("notify")) {
    return <Bell className="h-3 w-3 text-blue-500" />;
  }
  if (type.includes("case") || type.includes("search")) {
    return <Scale className="h-3 w-3 text-amber-500" />;
  }
  if (type.includes("schedule") || type.includes("consultation")) {
    return <Calendar className="h-3 w-3 text-emerald-500" />;
  }
  return <Sparkles className="h-3 w-3 text-indigo-500" />;
}

// UI-2: renders an action badge — type plus detail when present.
export default function ActionBadge({ action }: ActionBadgeProps) {
  return (
    <span
      data-testid="action-badge"
      className="inline-flex items-center gap-1.5 rounded-full border border-slate-200/80 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-2xs"
    >
      {getActionIcon(action.type)}
      <span>
        {action.type}
        {action.detail !== "" ? `: ${action.detail}` : ""}
      </span>
    </span>
  );
}