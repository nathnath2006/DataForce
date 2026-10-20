// Request/response shapes of docs/WORKSPACE-ONBOARDING-CONTRACT.md §1.2, from the generated API types.
import type * as G from "../api.gen";
import type { WorkspaceOut } from "../types";

export type WorkspaceKind = NonNullable<G.WorkspaceCreate["kind"]>;
export type WorkspaceCreateBody = Required<G.WorkspaceCreate>;
export type WorkspaceCreated = WorkspaceOut & { setup_state: NonNullable<G.WorkspaceOut["setup_state"]> };

export type SetupStatus = G.WorkspaceSetup;
export type SetupState = SetupStatus["state"];
export type StepId = "workspace" | "people" | "companies" | "contacts" | "deals" | "meetings" | "activity" | "logins";
