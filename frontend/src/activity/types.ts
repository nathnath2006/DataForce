import type * as G from "../api.gen";
// Mirrors backend/app/api/schemas_activity.py.
export type ActivityKind = "call" | "email" | "meeting" | "other";
export type Direction = "inbound" | "outbound";
export type TaskStatus = "suggested" | "open" | "in_progress" | "done" | "dismissed";

export interface Participant { id: string; full_name: string }
export interface ActivityOut {
  id: string; account_id: string; deal_id: string | null; kind: ActivityKind; direction: Direction | null;
  occurred_at: string; subject: string; body: string | null; source: string;
  author_id: string | null; author_name: string | null; participants: Participant[]; created_at: string;
  deal_name?: string | null; account_name?: string | null;
}
export interface ActivityCreate {
  kind: ActivityKind; direction?: Direction | null; occurred_at: string; subject: string;
  body?: string | null; deal_id?: string | null; participant_ids?: string[];
}
/** Generated shape; the server sends `status` as a plain string, narrowed here. */
export type TaskOut = Omit<G.TaskOut, "status"> & { status: TaskStatus };
export type TaskCreate = G.TaskCreate;
export type TaskUpdate = G.TaskUpdate;
export interface MoveStage { stage: string; changed_on?: string | null; lost_reason?: string | null }

export type TimelineKind = "stage" | "call" | "email" | "meeting" | "other" | "note" | "comment" | "task";
export interface TimelineItem {
  id: string; kind: TimelineKind; at: string; title: string; title_untrusted: boolean; summary: string | null;
  summary_untrusted: boolean; author_name: string | null; refs: Record<string, unknown>;
}
export interface TimelinePage { items: TimelineItem[]; next_before: string | null }
