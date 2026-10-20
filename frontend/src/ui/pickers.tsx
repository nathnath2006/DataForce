import { useEffect, useState } from "react";
import { api } from "../api";
import { useWs } from "../context";
import { Typeahead, type TypeaheadItem } from "./Typeahead";

/** Resolve the label of a chosen id (e.g. from the URL) once; typed picks set it directly. */
function usePicked(id: string, load: (id: string) => Promise<TypeaheadItem>) {
  const [item, setItem] = useState<TypeaheadItem | null>(null);
  useEffect(() => {
    if (!id) { setItem(null); return; }
    if (item?.id === id) return;
    const ac = new AbortController();
    load(id).then((r) => { if (!ac.signal.aborted) setItem(r); }, () => { if (!ac.signal.aborted) setItem({ id, label: "Unknown" }); });
    return () => { ac.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  return [item?.id === id ? item : null, setItem] as const;
}

interface PickerProps { id: string; onChange: (id: string, item: TypeaheadItem | null) => void; ariaLabel?: string; required?: boolean; autoFocus?: boolean }

/** Account typeahead: asks the server (`q`, `limit=20`) instead of loading every account. */
export function AccountPicker(p: PickerProps) {
  const { ws } = useWs();
  const [item, setItem] = usePicked(p.id, async (id) => {
    const a = await api.getAccount(ws.slug, id);
    return { id: a.id, label: a.name };
  });
  return (
    <Typeahead
      ariaLabel={p.ariaLabel ?? "Account"} placeholder="Search accounts…" required={p.required} autoFocus={p.autoFocus} value={item}
      search={async (text, signal) =>
        (await api.listAccounts(ws.slug, { q: text, limit: 20 }, signal)).items.map((a) => ({ id: a.id, label: a.name, hint: a.domain ?? undefined }))}
      onChange={(it) => { setItem(it); p.onChange(it?.id ?? "", it); }}
    />
  );
}

/** Contact typeahead, optionally limited to one account. */
export function ContactPicker(p: PickerProps & { accountId?: string }) {
  const { ws } = useWs();
  const [item, setItem] = usePicked(p.id, async (id) => {
    const c = await api.getContact(ws.slug, id);
    return { id: c.id, label: c.full_name };
  });
  return (
    <Typeahead
      ariaLabel={p.ariaLabel ?? "Contact"} placeholder="Search contacts…" required={p.required} autoFocus={p.autoFocus} value={item}
      search={async (text, signal) =>
        (await api.listContacts(ws.slug, { q: text, account_id: p.accountId, limit: 20 }, signal)).items
          .map((c) => ({ id: c.id, label: c.full_name, hint: c.account_name }))}
      onChange={(it) => { setItem(it); p.onChange(it?.id ?? "", it); }}
    />
  );
}
