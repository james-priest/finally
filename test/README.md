# FinAlly E2E Tests

Playwright (TypeScript) suite. Specs run serially in file-name order against one shared single-user backend, and `01-fresh-start` expects an untouched database.

## Docker (recommended)

From the repo root:

```bash
docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from playwright
docker compose -f test/docker-compose.test.yml down -v
```

The app runs with `LLM_MOCK=true`, the simulator (`MASSIVE_API_KEY` empty, root `.env` not loaded) and no persistent volume. The HTML report lands in `test/playwright-report/`.

## Local

Start the backend with a fresh database and the frontend built into `backend/static`:

```bash
rm -f db/finally.db
cd backend && MASSIVE_API_KEY= LLM_MOCK=true uv run uvicorn app.main:app --port 8000 --timeout-graceful-shutdown 2
```

Then, in `test/`:

```bash
npm install && npx playwright install chromium
# If the default browser cache is not writable, prefix install and test with PLAYWRIGHT_BROWSERS_PATH=0
npx playwright test                         # BASE_URL defaults to http://localhost:8000
BASE_URL=http://localhost:8001 npx playwright test e2e/07-api.spec.ts
```
