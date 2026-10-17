// Mirrors backend/app/api/schemas.py and backend/app/domain/schemas.py.
export type DealStage =
  | "prospecting" | "qualification" | "proposal" | "negotiation" | "closed_won" | "closed_lost";
export const DEAL_STAGES: DealStage[] = [
  "prospecting", "qualification", "proposal", "negotiation", "closed_won", "closed_lost",
];
export type LeadSource = "inbound" | "outbound" | "referral" | "partner" | "event" | "other";
export const LEAD_SOURCES: LeadSource[] = ["inbound", "outbound", "referral", "partner", "event", "other"];
export type Segment = "smb" | "midmarket" | "enterprise";
export const SEGMENTS: Segment[] = ["smb", "midmarket", "enterprise"];
export type RecordSource = "manual" | "demo" | "import" | "tamtam";
export type UserRole = "admin" | "user";
export type ChannelKind = "email" | "mobile";
export type Metric = "win_rate" | "cycle_days" | "deal_amount";
export type Dimension = "lead_source" | "segment" | "industry" | "region" | "owner" | "amount_band";
export type StatStatus = "verified" | "not_verified";

export interface Page<T> { items: T[]; total: number }

export type ErrorCode =
  | "not_found" | "invalid_input" | "conflict" | "forbidden" | "paid_lookup_refused"
  | "connector_not_configured" | "connector_error" | "internal";

export interface WorkspaceOut {
  slug: string; name: string; is_demo: boolean; created_at: string;
  n_accounts: number; n_contacts: number; n_deals: number;
}
export interface UserOut { id: string; display_name: string; email: string | null; role: UserRole }

export interface AccountOut {
  id: string; workspace_id: string; created_at: string; name: string; domain: string | null;
  industry: string | null; segment: Segment | null; employee_count: number | null;
  region: string | null; country: string | null; source: RecordSource; external_ref: string | null;
  n_contacts: number; n_deals: number; n_open_deals: number;
}
export interface AccountCreate {
  name: string; domain?: string | null; industry?: string | null; segment?: Segment | null;
  employee_count?: number | null; region?: string | null; country?: string | null;
}
export type AccountUpdate = Partial<AccountCreate>;

export interface ContactOut {
  id: string; workspace_id: string; created_at: string; account_id: string; full_name: string;
  title: string | null; reports_to_id: string | null; source: RecordSource; source_ref: string | null;
  title_function: string | null; title_seniority: string | null;
  account_name: string; reports_to_name: string | null; n_direct_reports: number;
  n_notes: number; n_channels: number;
}
export interface ContactCreate {
  account_id: string; full_name: string; title?: string | null; reports_to_id?: string | null;
}
export interface ContactUpdate { full_name?: string; title?: string | null }

export interface OrgChartNode {
  id: string; full_name: string; title: string | null; reports_to_id: string | null; source: string;
}
export interface OrgChartOut { account_id: string; account_name: string; nodes: OrgChartNode[] }

export interface DealOut {
  id: string; workspace_id: string; created_at: string; account_id: string; owner_id: string | null;
  name: string; amount_eur: string | number | null; stage: DealStage; lead_source: LeadSource | null;
  created_on: string; closed_on: string | null; lost_reason: string | null; source: RecordSource;
  account_name: string; owner_name: string | null; is_closed: boolean; cycle_days: number | null;
}
export interface DealCreate {
  account_id: string; owner_id?: string | null; name: string; amount_eur?: number | string | null;
  stage?: DealStage; lead_source?: LeadSource | null; created_on: string; closed_on?: string | null;
  lost_reason?: string | null;
}
export interface DealUpdate {
  owner_id?: string | null; name?: string; amount_eur?: number | string | null;
  lead_source?: LeadSource | null; created_on?: string; lost_reason?: string | null;
}

export interface NoteOut {
  id: string; workspace_id: string; author_id: string | null; body: string; created_at: string;
  corrects_id: string | null; deleted_at: string | null; deleted_by_id: string | null;
  author_name: string | null; deleted_by_name: string | null;
}

export interface StageTotals { count: number; amount_eur: number; n_with_amount: number }
export interface PipelineOut {
  n_deals: number; n_open: number; n_closed: number; n_won: number; n_lost: number;
  by_stage: Partial<Record<DealStage, StageTotals>>; total_amount_eur: number;
}

export interface GateConfig {
  confidence: number; fdr_alpha: number; min_n: number; min_wins: number; min_losses: number;
  max_ci_halfwidth_pts: number; max_ci_rel_halfwidth: number; bootstrap_resamples: number;
  random_seed: number;
}
export interface StatValue {
  metric: Metric; value: number | null; ci_low: number | null; ci_high: number | null; n: number;
  method: string; status: StatStatus; reasons: string[]; details: Record<string, unknown>;
}
export interface GroupStats {
  dimension: Dimension; group: string; n_deals: number; stats: Partial<Record<Metric, StatValue>>;
}
export interface EffectFinding {
  dimension: Dimension; group: string; metric: Metric; group_value: number | null;
  rest_value: number | null; diff: number | null; diff_ci_low: number | null;
  diff_ci_high: number | null; p_value: number | null; q_value: number | null; test: string;
  n_group: number; n_rest: number; direction: "higher" | "lower" | "none"; status: StatStatus;
  reasons: string[];
}
export interface ScanReport {
  workspace_id: string | null; created_at: string; n_deals: number; n_closed: number; n_open: number;
  gates: GateConfig; overall: Partial<Record<Metric, StatValue>>; groups: GroupStats[];
  findings: EffectFinding[]; missing: Record<string, number>; notes: string[];
}
export interface ScanOut { run_id: string; report: ScanReport }

export interface PricingOut { email: number; mobile: number; ceiling: number; assumed: boolean }
export interface ToolOut {
  name: string; description: string | null; read_only: boolean | null;
  destructive: boolean | null; allowed: boolean;
}
export interface ConnectorOut {
  provider: "tamtam"; status: "not_connected" | "connected" | "expired" | "error";
  enrichment_mode: "fake" | "tamtam" | "off"; secret_key_configured: boolean; resource: string;
  issuer: string | null; scope: string | null; connected_at: string | null;
  token_expires_at: string | null; checked_at: string | null; tools: ToolOut[] | null;
  last_error: string | null; pricing: PricingOut;
}
export interface ConnectStart { authorize_url: string }
export interface EnrichRequest { want: ChannelKind[]; confirm_paid: boolean; max_credits: number }
export interface ChannelOut {
  id: string; kind: ChannelKind; value: string; provider: string; credits_used: number;
  raw_tool: string | null; fetched_at: string;
}
export interface EnrichResponse {
  mode: "fake" | "tamtam"; channels: ChannelOut[]; credits_used: number; anomalous: boolean;
  notes: string[];
}
