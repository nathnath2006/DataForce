import { useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";
export const THEME_KEY = "df-theme";
const ORDER: ThemeChoice[] = ["system", "light", "dark"];

type Store = Pick<Storage, "getItem" | "setItem">;

export function nextTheme(t: ThemeChoice): ThemeChoice {
  return ORDER[(ORDER.indexOf(t) + 1) % ORDER.length] ?? "system";
}

function defaultStore(): Store | null {
  try { return localStorage; } catch { return null; }
}

/** Stored choice; anything missing, invalid or unreadable means "system". */
export function readTheme(store: Store | null = defaultStore()): ThemeChoice {
  try {
    const v = store?.getItem(THEME_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch { return "system"; }
}

export function saveTheme(t: ThemeChoice, store: Store | null = defaultStore()): void {
  try { store?.setItem(THEME_KEY, t); } catch { /* unavailable: the choice lasts for this page only */ }
}

export function applyTheme(t: ThemeChoice, root: { dataset: Record<string, string | undefined> } = document.documentElement): void {
  if (t === "system") delete root.dataset["theme"];
  else root.dataset["theme"] = t;
}

/** Called from main.tsx before the first render. */
export function initTheme(): void {
  applyTheme(readTheme());
}

/** The applied theme (follows the toggle): for widgets that take an explicit mode. */
export function useThemeChoice(): ThemeChoice {
  const read = (): ThemeChoice => {
    const t = document.documentElement.dataset["theme"];
    return t === "light" || t === "dark" ? t : "system";
  };
  const [t, setT] = useState<ThemeChoice>(read);
  useEffect(() => {
    const obs = new MutationObserver(() => setT(read()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  return t;
}

const LABEL: Record<ThemeChoice, string> = { system: "System", light: "Light", dark: "Dark" };

export function ThemeToggle() {
  const [t, setT] = useState<ThemeChoice>(() => readTheme());
  const n = nextTheme(t);
  return (
    <button
      type="button" className="theme-toggle"
      aria-label={`Theme: ${LABEL[t]}. Switch to ${LABEL[n]}.`} title={`Theme: ${LABEL[t]}`}
      onClick={() => { setT(n); saveTheme(n); applyTheme(n); }}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {t === "dark" ? <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" /> : t === "light"
          ? <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5" /></>
          : <><circle cx="12" cy="12" r="8" /><path d="M12 4v16" /></>}
      </svg>
    </button>
  );
}
