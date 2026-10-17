import { createContext, useContext } from "react";
import type { UserOut, WorkspaceOut } from "./types";

export interface Ctx {
  ws: WorkspaceOut;
  users: UserOut[];
  actingAs: string | null;
  refreshUsers: () => void;
  refreshWorkspaces: () => void;
}
export const WsContext = createContext<Ctx | null>(null);
export function useWs(): Ctx {
  const c = useContext(WsContext);
  if (!c) throw new Error("outside workspace");
  return c;
}
