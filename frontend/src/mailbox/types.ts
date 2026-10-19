export type MailProvider = "gmail" | "outlook";
export type MessageState = "suggested" | "linked" | "ignored";

export interface MailboxCounts { suggested: number; unmatched: number; linked: number; ignored: number }

export interface MailboxConnectionOut {
  provider: MailProvider;
  label: string;
  status: "not_configured" | "configured" | "connected" | "needs_reconnect";
  client_source: "settings" | "env" | null;
  secret_key_configured: boolean;
  account_email: string | null;
  redirect_uri: string;
  last_sync_at: string | null;
  last_error: string | null;
  counts: MailboxCounts;
}

export interface MailboxStatusOut {
  connections: MailboxConnectionOut[];
  lookback_days: number;
  max_messages: number;
}

export interface MailboxSyncResultOut {
  run_id: string;
  fetched: number;
  candidates: number;
  new: number;
  suggested: number;
  errors: string[];
}

export interface MailboxMessageOut {
  id: string;
  provider: MailProvider;
  from_addr: string;
  to_addrs: string[];
  cc_addrs: string[];
  sent_at: string;
  subject: string;
  snippet: string;
  state: MessageState;
  suggested_deal_id: string | null;
  score: number | null;
  reasons: string[];
  linked_activity_id: string | null;
}
