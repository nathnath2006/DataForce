import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The proxy keeps the browser's Host and Origin (no changeOrigin), so the backend's
// Host / Origin checks see the dev origin http://127.0.0.1:5173.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8800", changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: false },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
