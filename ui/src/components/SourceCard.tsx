import { ExternalLink, FileText } from "lucide-react";
import type { Source } from "../api/types";

interface SourceCardProps {
  source: Source;
}

// UI-2: renders every field of a citation source — id, text, source, distance.
export default function SourceCard({ source }: SourceCardProps) {
  return (
    <div
      data-testid="source-card"
      className="flex flex-col justify-between rounded-lg border border-slate-200/80 bg-white p-2.5 text-xs text-slate-600 shadow-2xs transition-colors hover:border-slate-300"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <FileText className="h-3.5 w-3.5 shrink-0 text-blue-600" />
          <span className="font-semibold text-slate-800 truncate">{source.id}</span>
        </div>
        {source.url ? (
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-blue-600 hover:text-blue-700 underline truncate max-w-[50%]"
          >
            <span className="truncate">{source.source}</span>
            <ExternalLink className="h-3 w-3 shrink-0" />
          </a>
        ) : (
          <span className="text-slate-400 truncate">{source.source}</span>
        )}
      </div>
      <p className="mt-1.5 line-clamp-3 text-slate-700 leading-normal">{source.text}</p>
      <div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-1 text-[11px] text-slate-400">
        <span>distance: {source.distance}</span>
      </div>
    </div>
  );
}