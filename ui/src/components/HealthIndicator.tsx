// Compact API status pill rendered in the ChatView header (UI-5).
// ok → "connected"; degraded → "degraded"; unknown (first check pending) → "checking".

import type { HealthStatus } from "../hooks/useHealth";

const STATUS_LABEL: Record<HealthStatus, string> = {
  ok: "connected",
  degraded: "degraded",
  unknown: "checking",
};

const STATUS_TONE: Record<HealthStatus, string> = {
  ok: "bg-emerald-100 text-emerald-700",
  degraded: "bg-rose-100 text-rose-700",
  unknown: "bg-slate-100 text-slate-500",
};

const STATUS_DOT: Record<HealthStatus, string> = {
  ok: "bg-emerald-500",
  degraded: "bg-rose-500",
  unknown: "bg-slate-400",
};

export default function HealthIndicator({ status }: { status: HealthStatus }) {
  return (
    <span
      data-testid="health-indicator"
      data-status={status}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_TONE[status]}`}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[status]}`} />
      {STATUS_LABEL[status]}
    </span>
  );
}