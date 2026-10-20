import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import { authApi, type AuthMembership, type AuthUser, type Me } from "./api";

export interface AuthState {
  user: AuthUser | null;
  /** The signed-in user's membership in the workspace of the current URL, if any. */
  membership: AuthMembership | null;
  memberships: AuthMembership[];
  setupNeeded: boolean;
  isAdmin: boolean;
  loading: boolean;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
  /** Used by the login and setup pages after a successful call. */
  setMe: (me: Me) => void;
}

const noop = async () => {};
const Ctx = createContext<AuthState>({
  user: null, membership: null, memberships: [], setupNeeded: false, isAdmin: false, loading: true,
  signOut: noop, refresh: noop, setMe: () => {},
});

export function useAuth(): AuthState {
  return useContext(Ctx);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [setupNeeded, setSetupNeeded] = useState(false);
  const [loading, setLoading] = useState(true);
  const { pathname } = useLocation();
  const slug = /^\/w\/([^/]+)/.exec(pathname)?.[1] ?? null;

  const refresh = useCallback(async () => {
    try {
      const st = await authApi.status();
      setSetupNeeded(st.setup_needed);
      setMe(st.signed_in ? await authApi.me() : null);
    } catch {
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const signOut = useCallback(async () => {
    try { await authApi.logout(); } catch { /* the session may already be gone */ }
    setMe(null);
    window.location.assign("/login");
  }, []);

  const value = useMemo<AuthState>(() => {
    const memberships = me?.memberships ?? [];
    const membership = slug ? memberships.find((m) => decodeURIComponent(slug) === m.workspace_slug) ?? null : null;
    return {
      user: me?.user ?? null, membership, memberships, setupNeeded, loading, signOut, refresh,
      isAdmin: !!me && (me.user.is_admin || membership?.role === "admin"),
      setMe: (m) => { setMe(m); setSetupNeeded(false); },
    };
  }, [me, slug, setupNeeded, loading, signOut, refresh]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
