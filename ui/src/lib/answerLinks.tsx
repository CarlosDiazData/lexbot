import type { ReactNode } from "react";
import type { Source } from "../api/types";

// Presentation layer for the agent's [slug] citation contract: turns inline
// [slug] tags into real links when the slug was actually cited by the agent.
// Unknown tags stay literal — never linkified (LLM hallucination guard).
export function linkifyAnswer(text: string, sources: Source[]): ReactNode[] {
  const urlBySlug = new Map(sources.map((s) => [s.source, s.url]));

  const nodes: ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(/\[([^\]]+)\]/g)) {
    const slug = match[1];
    const url = urlBySlug.get(slug);
    if (!url) {
      continue;
    }
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index));
    }
    nodes.push(
      <a key={nodes.length} href={url} target="_blank" rel="noreferrer">
        {match[0]}
      </a>,
    );
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }
  return nodes;
}