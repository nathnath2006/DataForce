// M5 seam (docs/M5-LOGIN-AND-UI-CONTRACT.md). L1 replaces these stubs with the real auth context;
// the shell (U1) imports only from here.
export interface AuthUser { id: string; email: string; display_name: string; is_admin: boolean }
export interface AuthMembership { workspace_slug: string; role: "admin" | "rep"; see_all: boolean; delete_own: boolean; app_user_id: string | null }

export interface AuthState {
  user: AuthUser | null;
  membership: AuthMembership | null;
  isAdmin: boolean;
  loading: boolean;
  signOut: () => Promise<void>;
}

export function useAuth(): AuthState {
  return { user: null, membership: null, isAdmin: true, loading: false, signOut: async () => {} };
}

/** The user menu in the top bar (name, role, workspace, sign out). */
export function UserMenu() {
  return null;
}

/** Route guard: sends a signed-out visitor to /login (or /setup before the first admin). */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

/** /login: email and password. */
export function LoginPage() {
  return null;
}

/** /setup: shown once, while no admin exists. */
export function SetupPage() {
  return null;
}
