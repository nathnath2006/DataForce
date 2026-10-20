// Demo-mode API shapes (docs/M6-ACCOUNTS-ADMIN-CONTRACT.md section E). Local until api.gen.ts is regenerated.
export interface DemoIdentity { as: string; label: string; role: "admin" | "rep" }
export type DemoProvider = "gemini" | "anthropic";
export interface DemoAiKeyOut { provider: DemoProvider | null; model: string | null; set: boolean }
export interface DemoAiKeyIn { provider: DemoProvider; model: string; api_key: string }
export interface DemoStatusExtra { demo_available?: boolean }
