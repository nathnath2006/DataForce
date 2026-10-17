// Mirrors docs/M2B-CONTRACT.md section 5 (backend/app/api/schemas_{documents,themes}.py).
export interface SpeakerOut { name: string; contact_id: string | null; user_id: string | null }
export interface DocumentOut {
  id: string; account_id: string; account_name: string; deal_id: string | null; title: string;
  meeting_date: string | null; file_name: string | null; n_chars: number; n_chunks: number;
  language: string | null; speakers: SpeakerOut[]; theme_labels: string[]; created_at: string;
}
export interface ChunkOut {
  id: string; seq: number; speaker: string | null; contact_id: string | null; user_id: string | null;
  char_start: number; char_end: number;
}
export interface ChunkTheme { chunk_id: string; theme_id: string; label: string }
export interface DocumentDetail extends DocumentOut { text: string; chunks: ChunkOut[]; chunk_themes: ChunkTheme[] }

export type ThemeKind = string;
export interface ThemeExcerpt {
  chunk_id: string; document_id: string; account_id: string; account_name: string;
  meeting_date: string | null; speaker: string | null; text: string;
}
export interface ThemeOut {
  id: string; seq: number; label: string; description: string | null; kind: ThemeKind;
  named_by: "llm" | "keywords" | "lexicon"; top_terms: string[]; n_chunks: number; n_documents: number;
  n_accounts: number; excerpts: ThemeExcerpt[]; status: "exploratory";
  // known: a catalog sales theme detected by keywords (by code); discovered: a recurring topic
  // found in the remaining sentences.
  origin?: "known" | "discovered";
}
export interface ThemeRunOut {
  run_id: string; created_at: string; k: number; n_chunks_used: number; n_unassigned: number;
  dropped_themes: number; themes: ThemeOut[];
  known_themes?: string[];
}
export interface ThemeRunIn { k?: number; speakers?: "customer" | "all"; use_ai?: boolean }
