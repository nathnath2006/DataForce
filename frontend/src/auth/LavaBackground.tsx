import { useEffect, useRef } from "react";

/**
 * Faint decorative background: a wall of tiny round dots in gentle perspective, rolled by a slow
 * sea (a few low-frequency sines) and swollen by drifting lava-lamp blobs. Crests glint, a few in
 * the warm accent. Plain Canvas 2D, ~30 fps, paused when hidden, one static frame when the
 * visitor prefers reduced motion. Colours come from the CSS variables.
 */
const HORIZON = 0.28; // share of the height where the surface vanishes
const ROWS = 34;
const COLS = 76; // columns either side of the centre are COLS / 2
const BLOBS = [
  { u: 0.2, w: 0.3, fu: 0.07, fw: 0.05, r: 0.28 },
  { u: 0.7, w: 0.6, fu: 0.05, fw: 0.08, r: 0.22 },
  { u: 0.5, w: 0.8, fu: 0.09, fw: 0.04, r: 0.3 },
  { u: 0.85, w: 0.2, fu: 0.04, fw: 0.06, r: 0.18 },
];

const clamp = (v: number) => Math.max(0, Math.min(1, v));
const hash = (i: number, j: number) => {
  const s = Math.sin(i * 127.1 + j * 311.7) * 43758.5453;
  return s - Math.floor(s);
};

/** Surface height in 0..1 at normalised position (u across, w depth) and time t seconds. */
function field(u: number, w: number, t: number): number {
  let h = 0.5 + 0.17 * Math.sin(u * 7 + t * 0.5 + w * 3) + 0.14 * Math.sin(u * 3.1 - w * 6 - t * 0.37)
    + 0.1 * Math.sin((u + w) * 11 + t * 0.8);
  for (const b of BLOBS) {
    const du = u - (b.u + 0.18 * Math.sin(t * b.fu * 6.28 + b.w * 9));
    const dw = w - (b.w + 0.15 * Math.cos(t * b.fw * 6.28 + b.u * 9));
    h += 0.8 * Math.exp(-(du * du + dw * dw) / (b.r * b.r * 0.3)); // the wax: visible swells
  }
  return clamp(h / 1.6);
}

export function LavaBackground() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let W = 0, H = 0, raf = 0, last = 0;
    let colors = { base: "#0a6cff", glint: "#0057d9", warm: "#facc15" };

    const readColors = () => {
      const css = getComputedStyle(document.documentElement);
      const get = (n: string, d: string) => css.getPropertyValue(n).trim() || d;
      colors = { base: get("--primary", colors.base), glint: get("--primary-hover", colors.glint), warm: get("--highlight", colors.warm) };
    };
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      W = canvas.clientWidth;
      H = canvas.clientHeight;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      readColors();
      draw(last / 1000);
    };

    function draw(t: number) {
      ctx!.clearRect(0, 0, W, H);
      const top = H * HORIZON;
      for (let r = 0; r < ROWS; r++) {
        const d = (r + 1) / ROWS; // 0 far .. 1 near
        const y = top + (H - top) * Math.pow(d, 1.7);
        const spacing = (0.12 + d * 1.05) * (W / 56);
        const size = 0.6 + d * 3.2;
        for (let c = -COLS / 2; c <= COLS / 2; c++) {
          const x = W / 2 + c * spacing;
          if (x < -size || x > W + size) continue;
          const h = field(0.5 + c / COLS, d, t);
          const crest = clamp((h - 0.62) / 0.3);
          const rad = size * (0.25 + 0.95 * h);
          ctx!.globalAlpha = (0.04 + 0.24 * h + 0.3 * crest) * (0.25 + 0.75 * d);
          ctx!.fillStyle = crest > 0.55 && hash(c, r) > 0.9 ? colors.warm : crest > 0.35 ? colors.glint : colors.base;
          ctx!.beginPath();
          ctx!.arc(x, y - h * d * 24, rad, 0, Math.PI * 2);
          ctx!.fill();
        }
      }
      ctx!.globalAlpha = 1;
    }

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (now - last < 33) return;
      last = now;
      draw(now / 1000);
    };
    const onVisibility = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden && !still) raf = requestAnimationFrame(frame);
    };

    last = 4000; // a pleasant still frame
    resize();
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", onVisibility);
    const theme = new MutationObserver(() => { readColors(); draw(last / 1000); });
    theme.observe(document.documentElement, { attributes: true });
    const scheme = window.matchMedia("(prefers-color-scheme: dark)");
    scheme.addEventListener("change", resize);
    onVisibility();
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
      scheme.removeEventListener("change", resize);
      theme.disconnect();
    };
  }, []);

  return <canvas ref={ref} className="auth-bg" aria-hidden="true" />;
}
