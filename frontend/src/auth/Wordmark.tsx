/** The DataForce wordmark: a small blue mark and the name. */
export function Wordmark() {
  return (
    <div className="wordmark" aria-label="DataForce">
      <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
        <rect width="24" height="24" rx="6" fill="var(--primary)" />
        <path d="M7 17V7h4.5a5 5 0 0 1 0 10z" fill="none" stroke="var(--primary-ink)" strokeWidth="2" strokeLinejoin="round" />
      </svg>
      <span>DataForce</span>
    </div>
  );
}
