export function pagerLabel(offset: number, shown: number, total: number): string {
  if (total === 0 || shown === 0) return "0 results";
  return `${(offset + 1).toLocaleString("en-US")}–${(offset + shown).toLocaleString("en-US")} of ${total.toLocaleString("en-US")}`;
}

export function Pager(p: { offset: number; limit: number; shown: number; total: number; onOffset: (o: number) => void }) {
  return (
    <nav className="row pager" aria-label="Pagination">
      <button disabled={p.offset <= 0} onClick={() => p.onOffset(Math.max(0, p.offset - p.limit))}>Previous</button>
      <span className="muted small" aria-live="polite">{pagerLabel(p.offset, p.shown, p.total)}</span>
      <button disabled={p.offset + p.limit >= p.total} onClick={() => p.onOffset(p.offset + p.limit)}>Next</button>
    </nav>
  );
}
