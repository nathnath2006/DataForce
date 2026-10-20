import type { ReactNode } from "react";
import { Navigate } from "react-router";
import { Loading } from "../ui";
import { useAuth } from "./context";

/** Route guard: sends a signed-out visitor to /login (or /setup before the first admin). */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading, setupNeeded } = useAuth();
  if (loading) return <main className="center"><Loading /></main>;
  if (setupNeeded) return <Navigate to="/setup" replace />;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
