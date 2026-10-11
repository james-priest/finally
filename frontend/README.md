# FinAlly Frontend

Next.js 16 (App Router) + TypeScript + Tailwind CSS 4, built as a static export and served by FastAPI.

## Commands

```bash
npm install
npm run build        # static export to out/ (index.html + _next/)
npm test             # Vitest + React Testing Library
npm run lint
npm run dev          # http://localhost:3000, /api proxied to the backend
```

Dev mode proxies `/api/*` to `BACKEND_URL` (default `http://localhost:8000`), so start the backend first:

```bash
cd ../backend && uv run uvicorn app.main:app --port 8000 --timeout-graceful-shutdown 2
```

## Layout

- `app/` - root layout, page, global theme (`globals.css`)
- `components/` - `Terminal` composes the header, watchlist, main chart, trade bar, positions table, heatmap, portfolio value chart and chat panel
- `lib/` - API client, types, formatting, live valuation, treemap, and `usePriceStream` (SSE)

Fonts are self-hosted via `@fontsource`, so the build needs no network access. Charts use Lightweight Charts. Element `data-testid`s follow `planning/TEAM_CONTRACT.md` §6.
