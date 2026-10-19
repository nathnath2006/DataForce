import { safeStorage } from "../ui";
import type { DealStage } from "../types";

export const DRAWER_KEY = "df.drawer";

/** Open or closed state of the assistant drawer: closed unless "open" was saved. A failing storage means closed. */
export function loadDrawerOpen(): boolean {
  return safeStorage("get", DRAWER_KEY) === "open";
}
export function saveDrawerOpen(open: boolean): void {
  safeStorage("set", DRAWER_KEY, open ? "open" : "closed");
}

export type StageState = "done" | "current" | "later" | "lost";
export interface RoadmapStep { key: string; label: string; state: StageState }

const OPEN_STAGES = ["prospecting", "qualification", "proposal", "negotiation"] as const;

/** The five pills of the roadmap. A lost deal does not say which stage it reached, so earlier pills stay "later". */
export function roadmapSteps(stage: DealStage): RoadmapStep[] {
  const idx = OPEN_STAGES.indexOf(stage as (typeof OPEN_STAGES)[number]);
  const steps: RoadmapStep[] = OPEN_STAGES.map((k, i) => ({
    key: k, label: k,
    state: stage === "closed_won" ? "done" : idx < 0 ? "later" : i < idx ? "done" : i === idx ? "current" : "later",
  }));
  const last: RoadmapStep =
    stage === "closed_lost" ? { key: "closed", label: "closed lost", state: "lost" }
    : stage === "closed_won" ? { key: "closed", label: "closed won", state: "done" }
    : { key: "closed", label: "closed", state: "later" };
  return [...steps, last];
}

interface DealLike { stage: DealStage; created_on: string; is_closed: boolean }

/** Most recent open deal, else the latest deal; null when there are none. */
export function pickRoadmapDeal<D extends DealLike>(deals: D[]): D | null {
  const latest = (xs: D[]) => xs.reduce<D | null>((b, d) => (b === null || d.created_on > b.created_on ? d : b), null);
  return latest(deals.filter((d) => !d.is_closed)) ?? latest(deals);
}
