import type { Source } from "../api/types";

interface SourceCardProps {
  source: Source;
}

// UI-2: renders every field of a citation source — id, text, source, distance.
export default function SourceCard({ source }: SourceCardProps) {
  return (
    <div data-testid="source-card" className="rounded-md border border-slate-200 bg-white p-2 text-xs text-slate-600">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold text-slate-700">{source.id}</span>
        <span className="text-slate-400">{source.source}</span>
      </div>
      <p className="mt-1 text-slate-700">{source.text}</p>
      <p className="mt-1 text-slate-400">distance: {source.distance}</p>
    </div>
  );
}