import { useEffect, useId, useRef, useState } from "react";
import { useDebounced } from "../ui";
import "./typeahead.css";

export interface TypeaheadItem { id: string; label: string; hint?: string }

export interface TypeaheadProps {
  /** The chosen item (controlled); null when nothing is chosen. */
  value: TypeaheadItem | null;
  onChange: (item: TypeaheadItem | null) => void;
  /** Server search: should send `q` and `limit=20`; must honour the signal. */
  search: (text: string, signal: AbortSignal) => Promise<TypeaheadItem[]>;
  ariaLabel: string;
  placeholder?: string;
  required?: boolean;
  disabled?: boolean;
  autoFocus?: boolean;
}

/** Async combobox: type to query the server (debounced, previous request aborted), pick with mouse or keys. */
export function Typeahead(p: TypeaheadProps) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<TypeaheadItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [active, setActive] = useState(0);
  const dq = useDebounced(text.trim(), 200);
  const listId = useId();
  const searchRef = useRef(p.search);
  searchRef.current = p.search;
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const ac = new AbortController();
    setFailed(false);
    searchRef.current(dq, ac.signal).then(
      (r) => { if (!ac.signal.aborted) { setItems(r); setActive(0); } },
      () => { if (!ac.signal.aborted) { setItems([]); setFailed(true); } },
    );
    return () => { ac.abort(); };
  }, [dq, open]);

  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", off);
    return () => { document.removeEventListener("mousedown", off); };
  }, [open]);

  const pick = (it: TypeaheadItem) => { p.onChange(it); setText(""); setOpen(false); };

  if (p.value) {
    return (
      <div className="ta ta-chosen">
        <span>{p.value.label}</span>
        <button type="button" disabled={p.disabled} aria-label={`Clear ${p.ariaLabel}`} onClick={() => p.onChange(null)}>Change</button>
        {p.required && <input tabIndex={-1} aria-hidden="true" required value="x" readOnly style={{ position: "absolute", opacity: 0, pointerEvents: "none", height: 0 }} />}
      </div>
    );
  }
  return (
    <div className="ta" ref={box}>
      <input
        type="text" role="combobox" aria-label={p.ariaLabel} aria-expanded={open} aria-controls={listId} aria-autocomplete="list"
        aria-activedescendant={open && items?.[active] ? `${listId}-${active}` : undefined}
        placeholder={p.placeholder ?? "Type to search…"} value={text} required={p.required} disabled={p.disabled}
        autoFocus={p.autoFocus} autoComplete="off"
        onChange={(e) => { setText(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((i) => Math.min(i + 1, (items?.length ?? 1) - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
          else if (e.key === "Enter" && open && items?.[active]) { e.preventDefault(); pick(items[active]); }
          else if (e.key === "Escape" && open) { e.stopPropagation(); setOpen(false); }
        }}
      />
      {open && (
        <ul className="ta-list" role="listbox" id={listId}>
          {items === null && <li className="ta-state">Searching…</li>}
          {failed && <li className="ta-state">Search failed.</li>}
          {items && !failed && items.length === 0 && <li className="ta-state">No match.</li>}
          {items?.map((it, i) => (
            <li key={it.id} id={`${listId}-${i}`} role="option" aria-selected={i === active} className="ta-opt"
              onMouseDown={(e) => { e.preventDefault(); pick(it); }} onMouseEnter={() => setActive(i)}>
              <span>{it.label}</span>{it.hint && <span className="ta-hint">{it.hint}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
