// M5 auth (docs/M5-LOGIN-AND-UI-CONTRACT.md). The shell and pages import only from here.
export type { AuthMembership, AuthUser } from "./api";
export { AuthProvider, useAuth } from "./context";
export type { AuthState } from "./context";
export { RequireAuth } from "./RequireAuth";
export { LoginPage } from "./LoginPage";
export { SetupPage } from "./SetupPage";
export { UserMenu } from "./UserMenu";
export { AdminOnly, useCanDelete, useSeesAll } from "./AdminOnly";
export { ForgotPage } from "./ForgotPage";
export { ResetPage } from "./ResetPage";
