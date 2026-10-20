import type { ReactNode } from "react";
import { Loading } from "../ui";
import { useAuth } from "./context";

/** Admin-only pages (Settings, Admin): a rep sees one plain sentence instead of failed requests. */
export function AdminOnly({ children }: { children: ReactNode }) {
  const { isAdmin, loading } = useAuth();
  if (loading) return <Loading />;
  if (!isAdmin) {
    return (
      <section className="stack">
        <h1>Managed by your administrator</h1>
        <p className="muted">Settings and administration are open to the workspace administrator only.</p>
      </section>
    );
  }
  return <>{children}</>;
}

/** May the signed-in member delete a record owned by `ownerId` (a CRM user id)? Mirrors the
 *  server's `Viewer.may_delete`; the server still decides. */
export function useCanDelete(): (ownerId: string | null | undefined) => boolean {
  const { isAdmin, membership } = useAuth();
  return (ownerId) =>
    isAdmin || (!!membership?.delete_own && !!ownerId && ownerId === membership.app_user_id);
}

/** May the signed-in member look at other reps' numbers (the admin, or *see all*)? The server decides. */
export function useSeesAll(): boolean {
  const { isAdmin, membership } = useAuth();
  return isAdmin || !!membership?.see_all;
}
