# DataForce frontend

Vite + React + TypeScript (strict) + react-router. No UI kit; hand-written CSS (`src/styles.css`, light and dark).

    npm ci            # scripts are ignored (.npmrc)
    npm run dev       # http://127.0.0.1:5173, /api proxied to 127.0.0.1:8800 (start the API first)
    npm run build     # tsc -b && vite build -> dist/ (served by FastAPI at /)
    npm run typecheck
    npm test          # vitest: org-chart tree, formatting, authorize_url check, API errors

Layout: `src/api.ts` typed client (mutations send `X-DataForce: 1`), `src/types.ts` mirrors
`backend/app/api/schemas.py`, `src/lib.ts` pure logic (tested), `src/pages/*` screens.
The CSP is `script-src 'self'; style-src 'self'`: no inline scripts or styles; no `dangerouslySetInnerHTML`.
Server text is rendered as text. Dependencies are pinned exactly.
