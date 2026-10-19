import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export interface DrawerScope { kind: "account" | "company"; id: string; name: string }
interface ScopeCtx { scope: DrawerScope | null; setScope: (s: DrawerScope | null) => void }

const Ctx = createContext<ScopeCtx>({ scope: null, setScope: () => {} });

export function ScopeProvider({ children }: { children: ReactNode }) {
  const [scope, setScope] = useState<DrawerScope | null>(null);
  const v = useMemo(() => ({ scope, setScope }), [scope]);
  return <Ctx.Provider value={v}>{children}</Ctx.Provider>;
}

export function useDrawerScope(): DrawerScope | null { return useContext(Ctx).scope; }

/** Detail pages call this: the drawer then asks about this record. Cleared when the page unmounts. */
export function useRegisterScope(kind: DrawerScope["kind"], id: string | undefined, name: string | undefined) {
  const { setScope } = useContext(Ctx);
  useEffect(() => {
    if (!id) return;
    setScope({ kind, id, name: name ?? "" });
    return () => setScope(null);
  }, [setScope, kind, id, name]);
}
