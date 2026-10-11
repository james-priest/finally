# FinAlly — AI Trading Workstation

A visually stunning AI-powered trading workstation that streams live market data, simulates portfolio trading, and integrates an LLM chat assistant that can analyze positions and execute trades via natural language.

Built entirely by coding agents as a capstone project for an agentic AI coding course.

## Features

- **Live price streaming** via SSE with green/red flash animations
- **Simulated portfolio** — $10k virtual cash, market orders, instant fills
- **Portfolio visualizations** — heatmap (treemap), P&L chart, positions table
- **AI chat assistant** — analyzes holdings, suggests and auto-executes trades
- **Watchlist management** — track tickers manually or via AI
- **Dark terminal aesthetic** — Bloomberg-inspired, data-dense layout

## Architecture

Single Docker container serving everything on port 8000:

- **Frontend**: Next.js (static export) with TypeScript and Tailwind CSS
- **Backend**: FastAPI (Python/uv) with SSE streaming
- **Database**: SQLite with lazy initialization
- **AI**: LiteLLM → OpenRouter (Cerebras inference) with structured outputs
- **Market data**: Built-in GBM simulator (default) or Massive API (optional)

## Quick Start

Requires Docker.

```bash
cp .env.example .env          # then set OPENROUTER_API_KEY
scripts/start_mac.sh          # builds the image if needed, runs it, opens http://localhost:8000
scripts/stop_mac.sh           # stops the container; data is kept
```

Windows (PowerShell): `scripts\start_windows.ps1` and `scripts\stop_windows.ps1`.

| Start option                    | Effect                                 |
| ------------------------------- | -------------------------------------- |
| `--build` / `-Build`            | Rebuild the image even if it exists    |
| `--no-open` / `-NoOpen`         | Do not open the browser                |

Without the scripts:

```bash
docker build -t finally .
docker run -d --name finally -v finally-data:/app/db -p 8000:8000 --env-file .env finally
# or: docker compose up --build
```

The SQLite database lives in the `finally-data` Docker volume and survives restarts. To reset it: `docker volume rm finally-data`.

## Environment Variables

| Variable             | Required | Description                                                          |
| -------------------- | -------- | -------------------------------------------------------------------- |
| `OPENROUTER_API_KEY` | Yes      | OpenRouter API key for AI chat                                       |
| `MASSIVE_API_KEY`    | No       | Massive (Polygon.io) key for real market data; omit to use simulator |
| `LLM_MOCK`           | No       | Set `true` for deterministic mock LLM responses (testing)            |

## Project Structure

```
finally/
├── frontend/    # Next.js static export
├── backend/     # FastAPI uv project
├── planning/    # Project documentation and agent contracts
├── test/        # Playwright E2E tests
├── db/          # SQLite volume mount (runtime)
└── scripts/     # Start/stop helpers
```

## License

See [LICENSE](LICENSE).
