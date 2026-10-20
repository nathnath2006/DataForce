// Mirrors backend/app/api/schemas_activity.py.
export type ActivityKind = "call" | "email" | "meeting" | "other";
export type Direction = "inbound" | "outbound";
export type TaskStatus = "suggested" | "open" | "done" | "dismissed";

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
export interface TaskOut {
  id: string; deal_id: string | null; account_id: string | null; title: string; due_on: string | null;
  status: TaskStatus; owner_id: string | null; owner_name: string | null; source: string;
  evidence: Record<string, unknown>; done_at: string | null; created_at: string;
  deal_name?: string | null; account_name?: string | null;
}
export interface TaskCreate { title: string; deal_id?: string | null; account_id?: string | null; due_on?: string | null }
export interface TaskUpdate { title?: string; due_on?: string | null; status?: "open" | "done" | "dismissed"; owner_id?: string | null }
export interface MoveStage { stage: string; changed_on?: string | null; lost_reason?: string | null }

export type TimelineKind = "stage" | "call" | "email" | "meeting" | "other" | "note" | "comment" | "task";
export interface TimelineItem {
  id: string; kind: TimelineKind; at: string; title: string; title_untrusted: boolean; summary: string | null;
  summary_untrusted: boolean; author_name: string | null; refs: Record<string, unknown>;
}
export interface TimelinePage { items: TimelineItem[]; next_before: string | null }
