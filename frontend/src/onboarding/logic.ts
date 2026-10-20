// Pure parts of the onboarding: slug, step list, and where the name's dots go.
import type { SetupStatus } from "./types";

export function slugify(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
}
export const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;

export const STEPS = [
  { id: "workspace", label: "Creating the workspace" },
  { id: "people", label: "Adding the sales team" },
  { id: "companies", label: "Companies and accounts" },
  { id: "contacts", label: "Contacts" },
  { id: "deals", label: "Deals" },
  { id: "meetings", label: "Notes and meeting transcripts" },
  { id: "activity", label: "Stage history, activities and tasks" },
  { id: "logins", label: "Demo sign-ins" },
] as const;

export type StepState = "done" | "current" | "todo" | "failed";

/** One state per step, from the server's answer only (null = nothing heard yet: the first step is current). */
export function stepStates(s: SetupStatus | null): StepState[] {
  if (s?.state === "ready") return STEPS.map(() => "done");
  let idx = s?.step ? STEPS.findIndex((x) => x.id === s.step) : -1;
  if (idx < 0) idx = Math.max(0, Math.min(STEPS.length - 1, s?.done ?? 0));
  const bad = s?.state === "failed" || s?.state === "interrupted";
  return STEPS.map((_, i) => (i < idx ? "done" : i === idx ? (bad ? "failed" : "current") : "todo"));
}

/** Share of the work the server reports as done, 0..1 (never invented). */
export function progressOf(s: SetupStatus | null): number {
  if (!s) return 0;
  if (s.state === "ready") return 1;
  return s.total > 0 ? Math.max(0, Math.min(1, s.done / s.total)) : 0;
}

/** Alpha channel of RGBA pixel data. */
export function alphaChannel(rgba: ArrayLike<number>): number[] {
  const out = new Array<number>(Math.floor(rgba.length / 4));
  for (let i = 0; i < out.length; i++) out[i] = rgba[i * 4 + 3] ?? 0;
  return out;
}

export interface Pt { x: number; y: number }

/**
 * Dot targets for a rendered text mask: the centre of every `step`-pixel cell whose alpha is at least
 * 128, left to right (so letters form in reading order). More than `max` cells are thinned evenly.
 */
export function sampleTargets(alpha: ArrayLike<number>, width: number, height: number, step: number, max: number): Pt[] {
  const pts: Pt[] = [];
  const s = Math.max(1, step);
  for (let y = 0; y < height; y += s) {
    for (let x = 0; x < width; x += s) {
      const cx = Math.min(width - 1, Math.floor(x + s / 2)), cy = Math.min(height - 1, Math.floor(y + s / 2));
      if ((alpha[cy * width + cx] ?? 0) >= 128) pts.push({ x: x + s / 2, y: y + s / 2 });
    }
  }
  let picked = pts;
  if (max > 0 && pts.length > max) picked = Array.from({ length: max }, (_, i) => pts[Math.floor((i * pts.length) / max)] as Pt);
  return picked.sort((a, b) => a.x - b.x || a.y - b.y);
}
