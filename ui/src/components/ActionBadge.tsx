import type { Action } from "../api/types";

interface ActionBadgeProps {
  action: Action;
}

// UI-2: renders an action badge — type plus detail when present.
export default function ActionBadge({ action }: ActionBadgeProps) {
  return (
    <span
      data-testid="action-badge"
      className="inline-block rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-700"
    >
      {action.type}
      {action.detail !== "" ? `: ${action.detail}` : ""}
    </span>
  );
}