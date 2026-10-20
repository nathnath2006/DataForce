import { q, request, w } from "../api";

export type SegmentKind = "ok" | "warn" | "bad" | "unknown";
export interface QualitySegment { kind: SegmentKind; label: string; count: number }
export interface QualityCheck { id: "managers" | "titles" | "amounts" | "companies"; label: string; total: number; segments: QualitySegment[] }
export interface QualityOut { checks: QualityCheck[] }

export const qualityApi = {
  get: (ws: string, owner?: string) => request<QualityOut>("GET", `${w(ws)}/quality${q({ owner })}`),
};
