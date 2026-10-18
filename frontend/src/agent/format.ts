// Snippet formatting for the MCP panel (docs/M3A-CONTRACT.md section 5). Plain text only.
export interface AgentConnect { claude_desktop: Record<string, unknown>; claude_code: string }
export interface AgentTool { name: string; description: string; read_only: boolean }
export interface AgentCall { at: string; tool: string; ok: boolean; rows: number | null; duration_ms: number | null }
export interface AgentInfo { connect: AgentConnect; tools: AgentTool[]; recent_calls: AgentCall[] }

/** The JSON a user pastes into claude_desktop_config.json (2-space indent, as the CLI prints). */
export function desktopSnippet(c: AgentConnect): string {
  return JSON.stringify(c.claude_desktop, null, 2);
}

/** First sentence of a tool description, capped, for the list. */
export function shortDescription(text: string, max = 140): string {
  const flat = text.replace(/\s+/g, " ").trim();
  const end = flat.search(/[.!?](\s|$)/);
  const first = end >= 0 ? flat.slice(0, end + 1) : flat;
  return first.length > max ? first.slice(0, max - 1) + "…" : first;
}

export function callSummary(c: AgentCall): string {
  const rows = c.rows == null ? "" : `, ${c.rows} row${c.rows === 1 ? "" : "s"}`;
  const ms = c.duration_ms == null ? "" : `, ${c.duration_ms} ms`;
  return `${c.tool}: ${c.ok ? "ok" : "error"}${rows}${ms}`;
}
