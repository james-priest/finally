# Backend Developer Guide

FinAlly's backend: a FastAPI app managed with `uv`. It serves `/api/*`, the SSE price stream, and the static frontend, all on port 8000. The spec is `../planning/PLAN.md`. The contracts that other agents depend on live in `../planning/` (cross-team API shapes in `TEAM_CONTRACT.md`); this guide covers working inside `backend/`.

## Setup and Commands

Run everything from `backend/`:

```bash
uv sync                                    # Python 3.12 (.python-version) + locked deps (uv.lock)
uv run pytest                              # 190 tests, ~3s, no network or API keys needed
uv run ruff check app db tests demos       # lint
uv run ruff format app db tests demos      # format (line length 120)
uv run mypy app db demos                   # types
uv run uvicorn app.main:app --reload --timeout-graceful-shutdown 2   # http://localhost:8000
uv run python -m demos.market_simulator    # live terminal dashboard of the simulator (Ctrl+C to quit)
```

**Before you call a change done:** `pytest`, `ruff check`, `ruff format --check` and `mypy` must all be clean.

**Environment variables:** the repo-root `.env` holds them (see `../.env.example`). Docker passes it with `--env-file`. Locally, use `uv run --env-file ../.env ...`.

| Variable               | Effect                                                                    |
| ---------------------- | ------------------------------------------------------------------------- |
| `MASSIVE_API_KEY`      | Set and non-empty → real prices from Massive. Otherwise → the simulator   |
| `MASSIVE_POLL_SECONDS` | Massive snapshot poll interval (default 15, minimum 1)                    |
| `OPENROUTER_API_KEY`   | LLM chat (PLAN.md §9)                                                     |
| `LLM_MOCK`             | `true` → deterministic mock LLM replies (rules in TEAM_CONTRACT.md §5)    |
| `DB_PATH`              | SQLite file (default `../db/finally.db`; Docker `/app/db/finally.db`)     |
| `STATIC_DIR`           | Static frontend served at `/` if it exists (default `static/`)            |

For predictable local runs (and E2E), start with `MASSIVE_API_KEY= LLM_MOCK=true` to force the simulator and the mock LLM.

## Layout

```
app/
  main.py                  # FastAPI app, lifespan (init DB, market data, snapshot task), /api/health, static mount
  dependencies.py          # PriceCacheDep, MarketSourceDep: inject shared objects into routes
  routes/                  # one APIRouter per area: stream, portfolio, watchlist, chat; tickers.py = 422 on bad ticker
  services/market/         # market data: PriceCache, MarketDataSource, simulator, Massive client
  services/portfolio.py    # execute_trade, get_portfolio, snapshots; raises TradeError
  services/watchlist.py    # list/add/remove; raises WatchlistError
  services/llm/            # chat: schema, prompt + context, LiteLLM client, mock, orchestration
db/                        # SQLite: schema.sql, init_db + seed, sync data-access functions (`import db`)
demos/                     # runnable demos (dev only)
tests/                     # mirrors app/ and db/; demos are tested in tests/demos/
```

The REST and chat flows share `services/portfolio.py` and `services/watchlist.py`: the LLM never trades or edits the watchlist any other way.

## Conventions

- **Async FastAPI, typed throughout.** Ruff rules E, F, W, I, B, UP, SIM, ASYNC and RUF. Match the surrounding code: short docstrings that say why, and comments only where the reason isn't obvious.
- **Shared objects live on `app.state` and are created in the lifespan.** Routes get them through the `Annotated` dependencies in `dependencies.py`, never through module globals. Add a dependency there for each new shared service.
- **One event loop, one process.** Run blocking I/O (sync HTTP clients, slow file work) in `asyncio.to_thread`. The small SQLite queries in the services run directly on the loop on purpose: a trade's read-validate-write has no `await`, so concurrent trades can't interleave. Keep it that way. Write in-memory state only from the loop thread. Run a single uvicorn worker: prices live in process memory.
- **Background tasks never die.** Catch, log (`logger = logging.getLogger(__name__)`) and retry. Never let an exception end a loop silently.
- **Always pass `--timeout-graceful-shutdown 2` to uvicorn.** SSE streams never end on their own, so without it a shutdown waits for every open browser tab. The Docker `CMD` is in PLAN.md §11.

## Market Data: How to Use It

Import only from `app.services.market`: `PriceCache`, `PriceUpdate`, `MarketDataSource`, `normalize_ticker` and `create_market_data_source`. Nothing outside that package should know whether the simulator or Massive is running.

| Need                                   | Do this                                                                                                     |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| A ticker from a request or the LLM     | `normalize_ticker(raw)`. On `ValueError`, answer **422**                                                     |
| Current price                          | `cache.get_price(t)`. It **can be `None`** (unknown ticker on Massive, or Massive down since startup)        |
| Full quote (watchlist, LLM context)    | `cache.get(t)` returns a `PriceUpdate`; `.to_dict()` gives the SSE/REST shape                                 |
| After a watchlist change or a trade    | `await source.sync_tickers(db.tracked_tickers())`, where the tracked set is the watchlist plus open positions. Idempotent |
| A trade                                | `await source.add_ticker(t)`, then read the price. No price → **400**. Call `sync_tickers(...)` in a `finally` |
| Valuing a position with no price       | Use its `avg_cost`                                                                                          |

`add_ticker` prices immediately on the simulator. On Massive it waits at most 3s and makes no call while the API is failing. `../planning/MARKET_DATA_DESIGN.md` §11.6 has ready-made sketches of the watchlist routes, trade execution, valuation and the LLM-context helper.

## Testing

- **Async tests need no decorators** (pytest-asyncio auto mode): write `async def test_...`.
- **Each test gets its own temp SQLite file** (autouse `temp_db` fixture in `tests/conftest.py` sets `DB_PATH`).
- **No network in tests.** LiteLLM is monkeypatched; `client.py` sets `LITELLM_LOCAL_MODEL_COST_MAP` so importing litellm makes no network call. Inject fakes through constructors: `MassiveDataSource(..., client=FakeClient(...))`, `SimulatorDataSource(..., simulator=GBMSimulator(rng=random.Random(seed)))`. Use fixed seeds for anything random.
- **Routes:** run the lifespan with `app.router.lifespan_context(app)` and call the app through `httpx.ASGITransport` (see `tests/test_main.py`). Starlette's `TestClient` emits a deprecation warning with this httpx, so avoid it.
- **Streaming (SSE):** use a real uvicorn and httpx, through the `start_server()` helper in `tests/routes/test_stream.py`.
- **When fixing a bug, add a test that fails without the fix.** Avoid fixed sleeps for background work: poll with a deadline instead.

## Further Reading

| Document                                     | Read it for                                                                                   |
| -------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `../planning/PLAN.md`                        | The spec: endpoints (§8), database schema (§7), LLM (§9), Docker (§11)                        |
| `../planning/TEAM_CONTRACT.md`               | REST and chat response shapes, ownership, LLM mock rules, DB and service APIs                 |
| `../planning/MARKET_DATA_SUMMARY.md`         | Market data status, the SSE payload and `/api/health` contracts, test coverage, known limitations |
| `../planning/MARKET_DATA_DESIGN.md`          | Why market data works the way it does, module by module; §11.6 sketches for new routes         |
| `../planning/MASSIVE_API.md`                 | Massive API reference: plans, endpoints, client behaviour                                     |
