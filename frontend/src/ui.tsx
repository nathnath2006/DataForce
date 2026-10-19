import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "./lib";

/** Load data; `reload()` refetches. Stale responses are dropped. */
export function useLoad<R>(fn: () => Promise<R>, deps: unknown[]) {
  const [data, setData] = useState<R | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const tick = useRef(0);
  const [n, setN] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);
  useEffect(() => {
    const id = ++tick.current;
    setLoading(true);
    run().then(
      (d) => { if (id === tick.current) { setData(d); setError(null); setLoading(false); } },
      (e: unknown) => {
        if (id === tick.current) { setError(toApiError(e)); setLoading(false); }
      },
    );
  }, [run, n]);
  return { data, error, loading, reload: () => setN((x) => x + 1) };
}

export function toApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, "network_error", e instanceof Error ? e.message : "Unexpected error");
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const e = toApiError(error);
  return <div className="note err" role="alert"><strong>{e.code.replace(/_/g, " ")}</strong>: {e.message}</div>;
}

export function Loading() { return <p className="muted">Loading…</p>; }

export function Modal(props: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);
  return (
    <dialog ref={ref} className={props.wide ? "wide" : ""} onClose={props.onClose} onCancel={props.onClose}>
      <div className="dlg-head">
        <h2>{props.title}</h2>
        <button type="button" className="ghost" onClick={props.onClose} aria-label="Close">×</button>
      </div>
      <div className="dlg-body">{props.children}</div>
    </dialog>
  );
}

/** Async action wrapper that tracks busy and error. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const run = async <R,>(fn: () => Promise<R>): Promise<R | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(toApiError(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run, clear: () => setError(null) };
}

export function Confirm(props: {
  title: string; children: ReactNode; confirmLabel: string; danger?: boolean;
  /** When set, the user must type this text exactly before the button is enabled. */
  typeToConfirm?: string; onConfirm: () => Promise<unknown> | void; onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const a = useAction();
  const ok = props.typeToConfirm === undefined || typed === props.typeToConfirm;
  return (
    <Modal title={props.title} onClose={props.onClose}>
      <div className="stack">
        {props.children}
        {props.typeToConfirm !== undefined && (
          <label>
            Type <code>{props.typeToConfirm}</code> to confirm
            <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </label>
        )}
        <ErrorNote error={a.error} />
        <div className="row end">
          <button type="button" onClick={props.onClose}>Cancel</button>
          <button
            type="button" className={props.danger ? "danger" : "primary"} disabled={!ok || a.busy}
            onClick={() => void a.run(async () => { await props.onConfirm(); props.onClose(); })}
          >
            {props.confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}

export function Field(props: { label: string; children: ReactNode }) {
  return <label>{props.label}{props.children}</label>;
}

export function Tag({ children, kind }: { children: ReactNode; kind?: "ok" | "warn" | "mute" | "bad" }) {
  return <span className={`tag ${kind ?? ""}`}>{children}</span>;
}

/** Marks AI-made content. Never clickable; the item keeps its own honest-state styling. */
export function AiBadge({ children }: { children: ReactNode }) {
  return <span className="ai-pill">{children}</span>;
}

export function Empty({ children }: { children: ReactNode }) { return <p className="muted empty">{children}</p>; }

export function emptyToNull(s: string): string | null {
  const t = s.trim();
  return t === "" ? null : t;
}

export function useDebounced<V>(v: V, ms = 250): V {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

export function todayIso(): string { return new Date().toISOString().slice(0, 10); }

export function safeStorage(op: "get" | "set" | "remove", key: string, value?: string): string | null {
  try {
    if (op === "get") return localStorage.getItem(key);
    if (op === "set") localStorage.setItem(key, value ?? "");
    else localStorage.removeItem(key);
  } catch { /* storage unavailable: fall back to memory only */ }
  return null;
}
