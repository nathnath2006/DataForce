import type { AskCitation } from "../types";

export type Segment =
  | { type: "text"; text: string }
  | { type: "ref"; ref: string; label: string; known: boolean };

const REF = /\[([FDCNM]\d{1,4})\]/g;

/**
 * Split an answer into plain text and ref chips. Output is data only (never HTML); the caller
 * renders every segment as React text. A ref with no citation keeps its own id as label.
 */
export function parseAnswer(answer: string, citations: AskCitation[]): Segment[] {
  const labels = new Map(citations.map((c) => [c.ref, c.label]));
  const out: Segment[] = [];
  let last = 0;
  for (const m of answer.matchAll(REF)) {
    const idx = m.index ?? 0;
    if (idx > last) out.push({ type: "text", text: answer.slice(last, idx) });
    const ref = m[1] ?? "";
    const known = labels.has(ref);
    out.push({ type: "ref", ref, label: labels.get(ref) ?? ref, known });
    last = idx + m[0].length;
  }
  if (last < answer.length) out.push({ type: "text", text: answer.slice(last) });
  return out;
}
