import type { ChunkOut, ChunkTheme } from "./types";

export interface Seg { text: string; themeId: string | null; label: string | null }
export interface Turn { speaker: string | null; segs: Seg[] }

const isHigh = (c: number) => c >= 0xd800 && c <= 0xdbff;
const isLow = (c: number) => c >= 0xdc00 && c <= 0xdfff;

/** Clamp an offset into [0, len] and move it off the middle of a surrogate pair (never cut a character). */
export function safeOffset(text: string, i: number, dir: "back" | "forward"): number {
  if (!Number.isFinite(i)) return 0;
  let o = Math.min(Math.max(Math.trunc(i), 0), text.length);
  if (o > 0 && o < text.length && isLow(text.charCodeAt(o)) && isHigh(text.charCodeAt(o - 1))) {
    o += dir === "back" ? -1 : 1;
  }
  return o;
}

/**
 * Cut the transcript into speaker turns from chunk offsets. Consecutive chunks of one speaker form a
 * turn. Chunks are clipped so overlapping ranges never repeat text; text between chunks (for example
 * a "Name:" label) stays in the turn that follows, and text after the last chunk joins the last turn.
 * Concatenating every segment gives back the original text exactly.
 */
export function buildTurns(text: string, chunks: ChunkOut[], themes: ChunkTheme[]): Turn[] {
  const themeOf = new Map<string, ChunkTheme>();
  for (const t of themes) if (!themeOf.has(t.chunk_id)) themeOf.set(t.chunk_id, t);
  const sorted = [...chunks].sort((a, b) => a.char_start - b.char_start || a.seq - b.seq);
  const turns: Turn[] = [];
  let cursor = 0;
  let pending = "";
  const push = (turn: Turn, s: string, th: ChunkTheme | null) => {
    if (!s) return;
    const last = turn.segs[turn.segs.length - 1];
    const id = th ? th.theme_id : null;
    if (last && last.themeId === id) last.text += s;
    else turn.segs.push({ text: s, themeId: id, label: th ? th.label : null });
  };
  for (const c of sorted) {
    const start = Math.max(safeOffset(text, c.char_start, "back"), cursor);
    const end = safeOffset(text, c.char_end, "forward");
    if (end <= start) continue;
    pending += text.slice(cursor, start);
    const last = turns[turns.length - 1];
    let turn: Turn;
    if (last && last.speaker === c.speaker) {
      turn = last;
      push(turn, pending, null);
    } else {
      turn = { speaker: c.speaker, segs: [] };
      turns.push(turn);
      push(turn, pending, null);
    }
    pending = "";
    push(turn, text.slice(start, end), themeOf.get(c.id) ?? null);
    cursor = end;
  }
  const rest = pending + text.slice(cursor);
  if (turns.length === 0) return text ? [{ speaker: null, segs: [{ text, themeId: null, label: null }] }] : [];
  push(turns[turns.length - 1]!, rest, null);
  return turns;
}

/** The segments of a turn as shown under its speaker label: the leading "Name:" (or
 *  "**Name:**") that repeats the label, and the blank line before it, are dropped from the first
 *  segment. buildTurns itself stays lossless; this only affects display. */
export function displaySegs(turn: Turn): Turn["segs"] {
  const [first, ...rest] = turn.segs;
  if (!first) return [];
  let text = first.text.replace(/^\s+/, "");
  if (turn.speaker) {
    const name = turn.speaker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    text = text.replace(new RegExp(`^(?:\\*\\*)?\\s*${name}\\s*(?:\\*\\*)?\\s*:\\s*(?:\\*\\*)?\\s*`), "");
  }
  return text ? [{ ...first, text }, ...rest] : rest;
}

/** Distinct themes of a document in first-seen order (for the legend). */
export function legend(themes: ChunkTheme[]): { id: string; label: string; cls: string }[] {
  const seen = new Map<string, string>();
  for (const t of themes) if (!seen.has(t.theme_id)) seen.set(t.theme_id, t.label);
  return [...seen].map(([id, label], i) => ({ id, label, cls: themeClass(i) }));
}

export const THEME_CLASSES = 6;
export const themeClass = (i: number): string => `th${((i % THEME_CLASSES) + THEME_CLASSES) % THEME_CLASSES}`;

// ---- formatting ----
export function formatDate(d: string | null | undefined): string {
  if (!d) return "no date";
  const t = new Date(d);
  return Number.isNaN(t.getTime()) ? d : t.toISOString().slice(0, 10);
}
export function exactCount(n: number, noun: string): string {
  return `${n.toLocaleString("en-IE")} ${noun}${n === 1 ? "" : "s"}`;
}
export function clampK(v: number): number {
  if (!Number.isFinite(v)) return 8;
  return Math.min(30, Math.max(2, Math.round(v)));
}
export function speakerNames(s: { name: string }[]): string {
  return s.map((x) => x.name).join(", ");
}
