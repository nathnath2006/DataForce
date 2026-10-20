import { useEffect, useRef } from "react";
import { alphaChannel, sampleTargets, type Pt } from "./logic";

export type NameMode = "working" | "ready" | "failed";

/**
 * The creation animation: a field of round dots drifts, then gathers into the workspace name, left to
 * right, as `progress` (0..1, reported by the server) grows. At "ready" the name settles and one soft
 * glint sweeps across it; on "failed" the dots fall loose. Own Canvas 2D code (ideas only from
 * reactbits.dev backgrounds). Colours come from the CSS variables, the canvas follows devicePixelRatio,
 * and the frame loop stops on unmount or when the tab is hidden.
 */
interface Dot { x: number; y: number; vx: number; vy: number; hx: number; hy: number; ph: number; r: number; t: Pt | null; tf: number }

const GATHER_SECONDS = 1.2; // a full name never forms faster than this

export function NameCanvas(props: { text: string; progress: number; mode: NameMode }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const live = useRef(props);
  live.current = props;

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    let W = 0, H = 0, raf = 0, last = 0, shown = 0, readyAt = -1, fallAt = -1;
    let dots: Dot[] = [];
    let colors = { base: "#0a6cff", warm: "#facc15", ink: "#111418" };

    const readColors = () => {
      const css = getComputedStyle(document.documentElement);
      const get = (n: string, d: string) => css.getPropertyValue(n).trim() || d;
      colors = { base: get("--primary", colors.base), warm: get("--highlight", colors.warm), ink: get("--ink", colors.ink) };
    };

    const build = () => {
      const off = document.createElement("canvas");
      off.width = Math.max(1, Math.round(W));
      off.height = Math.max(1, Math.round(H));
      const oc = off.getContext("2d");
      const targets: Pt[] = [];
      if (oc) {
        const font = (px: number) => `700 ${px}px Helvetica, "Helvetica Neue", Arial, sans-serif`;
        let px = Math.min(110, H * 0.62);
        oc.font = font(px);
        const text = live.current.text || " ";
        const wide = oc.measureText(text).width;
        if (wide > W * 0.92) px = Math.max(18, (px * W * 0.92) / wide);
        oc.font = font(px);
        oc.textAlign = "center";
        oc.textBaseline = "middle";
        oc.fillStyle = "#000";
        oc.fillText(text, W / 2, H / 2);
        const img = oc.getImageData(0, 0, off.width, off.height);
        targets.push(...sampleTargets(alphaChannel(img.data), off.width, off.height, Math.max(3, Math.round(px / 16)), 1100));
      }
      const minX = targets[0]?.x ?? 0, spanX = Math.max(1, (targets[targets.length - 1]?.x ?? 1) - minX);
      const total = targets.length + 90; // the extra dots only drift
      dots = Array.from({ length: total }, (_, i) => {
        const t = targets[i] ?? null;
        const hx = Math.random() * W, hy = Math.random() * H;
        return { x: hx, y: hy, vx: 0, vy: 0, hx, hy, ph: Math.random() * 6.28, r: 1.4 + Math.random() * 1.6, t, tf: t ? (t.x - minX) / spanX : 2 };
      });
    };

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      W = canvas.clientWidth;
      H = canvas.clientHeight;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      readColors();
      build();
    };

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.05, (now - (last || now)) / 1000);
      last = now;
      const { progress, mode } = live.current;
      const time = now / 1000;
      const target = mode === "ready" ? 1 : progress;
      shown = Math.min(target, shown + dt / GATHER_SECONDS);
      if (mode === "ready" && readyAt < 0) readyAt = time;
      if (mode === "failed" && fallAt < 0) fallAt = time;
      const sweep = readyAt >= 0 && shown >= 1 ? ((time - readyAt) / 1.1) * (W + 160) - 80 : -1e9;

      ctx.clearRect(0, 0, W, H);
      for (const d of dots) {
        const gathered = d.t !== null && d.tf < shown + (shown >= 1 ? 1 : 0);
        if (fallAt >= 0) {
          d.vy += 900 * dt;
          d.x += d.vx * dt;
          d.y += d.vy * dt;
        } else {
          const gx = gathered ? d.t!.x : d.hx + Math.cos(time * 0.4 + d.ph) * 38;
          const gy = gathered ? d.t!.y : d.hy + Math.sin(time * 0.33 + d.ph * 1.7) * 26;
          const k = gathered ? 70 : 2.5, c = gathered ? 12 : 2.2;
          d.vx += ((gx - d.x) * k - d.vx * c) * dt;
          d.vy += ((gy - d.y) * k - d.vy * c) * dt;
          d.x += d.vx * dt;
          d.y += d.vy * dt;
        }
        if (d.y > H + 20) continue;
        const lit = Math.abs(d.x - sweep) < 46;
        ctx.globalAlpha = fallAt >= 0 ? 0.35 : gathered ? (lit ? 1 : 0.92) : 0.3;
        ctx.fillStyle = lit ? colors.warm : gathered && shown >= 1 ? colors.ink : colors.base;
        ctx.beginPath();
        ctx.arc(d.x, d.y, gathered ? d.r * (lit ? 1.35 : 1) : d.r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    };
    const onVisibility = () => {
      cancelAnimationFrame(raf);
      last = 0;
      if (!document.hidden) raf = requestAnimationFrame(frame);
    };

    resize();
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", onVisibility);
    const theme = new MutationObserver(readColors);
    theme.observe(document.documentElement, { attributes: true });
    const scheme = window.matchMedia("(prefers-color-scheme: dark)");
    scheme.addEventListener("change", readColors);
    onVisibility();
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
      scheme.removeEventListener("change", readColors);
      theme.disconnect();
    };
  }, [props.text]);

  return <canvas ref={ref} className="ob-canvas" role="img" aria-label={props.text} />;
}
