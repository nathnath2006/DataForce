import { useEffect, useState } from "react";
import type { Palette } from "./option";

/** Colors come from the CSS tokens at the time of the call: nothing is hard-coded here. */
export function readPalette(el: Element = document.documentElement): Palette {
  const cs = getComputedStyle(el);
  const v = (name: string) => cs.getPropertyValue(name).trim();
  return {
    primary: v("--primary"),
    series: [1, 2, 3, 4, 5, 6].map((i) => v(`--chart-${i}`)),
    ink: v("--ink"), inkSoft: v("--ink-soft"), hairline: v("--hairline"), surface: v("--surface"),
    font: v("--font") || "Helvetica, Arial, sans-serif",
  };
}

/** Bumps when the light/dark choice or the system scheme changes, so charts rebuild their option. */
export function useThemeVersion(): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    const bump = () => setN((x) => x + 1);
    const mo = new MutationObserver(bump);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener?.("change", bump);
    return () => { mo.disconnect(); mq?.removeEventListener?.("change", bump); };
  }, []);
  return n;
}
