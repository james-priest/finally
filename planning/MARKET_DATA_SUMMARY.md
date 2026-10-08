# Market Data Backend: Summary

What was built, tested and reviewed for FinAlly's market data subsystem (PLAN.md §6), and what the agents building on it need to know. Status as of 2026-10-08, `main` at `d7b118c`.

**Status: complete and ready.** The backend streams live prices from a simulator by default, or from the Massive API when a key is set. All 83 tests pass, and lint and type checks are clean. A live terminal dashboard (§7.1) shows the simulator in action. The one open item belongs to the database layer: replacing the placeholder ticker list (§10).

## 1. At a Glance

| Item                  | Value                                                                                         |
| --------------------- | --------------------------------------------------------------------------------------------- |
| Location              | `backend/app/services/market/`, `backend/app/routes/stream.py`, `backend/app/dependencies.py`, `backend/app/main.py` |
| Size                  | 741 lines of application code, 735 lines of tests                                            |
| Tests                 | **83 / 83 pass** in about 3s (76 for the backend, 7 for the terminal demo), with no network or API key needed |
| Coverage              | **99%** of `backend/app` (3 lines missed, all defensive branches)                            |
| Lint and types        | `ruff check`, `ruff format --check` and `mypy app demos`: all clean                          |
| Stack                 | Python 3.12, FastAPI 0.142.2 (native `fastapi.sse`), uvicorn 0.54.0, massive 2.8.0           |
| Pull requests         | #5 implementation · #7 code review · #8 review fixes                                        |
| Endpoints             | `GET /api/stream/prices` (SSE) · `GET /api/health`                                           |

## 2. How It Came Together

| Step | What happened                                                                                                                                                                        | Output                              |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------- |
| 1    | Research of the Massive (formerly Polygon.io) REST API: plans, endpoints, the Python client, error shapes                                                                             | MASSIVE_API.md                      |
| 2    | First drafts of the interface and the simulator                                                                                                                                      | MARKET_INTERFACE.md, MARKET_SIMULATOR.md (now archived) |
| 3    | Merged into one buildable design that fixed six bugs in the drafts (F1–F6) and made ten design changes (D1–D10)                                                                       | MARKET_DATA_DESIGN.md               |
| 4    | Implemented from the design, with 57 tests                                                                                                                                             | PR #5                               |
| 5    | Independent code review: live server runs, real-HTTP Massive checks, mutation spot-checks. Found 2 medium and 4 low issues, 6 test gaps and 4 nits                                     | MARKET_DATA_REVIEW.md, PR #7        |
| 6    | Every recommended action applied: 19 new tests (76 in all), ruff and mypy set up, docs updated                                                                                         | PR #8                               |

## 3. Architecture

```
  MASSIVE_API_KEY set? ──► create_market_data_source(cache)
                 ┌──────────────────┴──────────────────┐
                 ▼                                     ▼
       SimulatorDataSource                     MassiveDataSource
       tick every 0.5s (GBMSimulator)          snapshot poll every 15s, or hourly
                                               end-of-day closes on the free plan
                 └──────────────────┬──────────────────┘
                                    ▼  cache.update(ticker, price, prev_close)
                              PriceCache  (latest PriceUpdate per ticker + version)
                ┌───────────────────┼────────────────────────────┐
                ▼                   ▼                            ▼
       GET /api/stream/prices   trade fills                portfolio value, snapshots,
       (pushes on each change)  (cache price)              watchlist, LLM context
```

The rules:

1. **One writer, many readers.** Only the active source writes to the cache.
2. **Source-agnostic.** Nothing outside `services/market/` knows which source is running; `/api/health` reports it for diagnostics only.
3. **Everything on the event loop thread**, so the cache needs no lock. Massive's synchronous HTTP client runs in `asyncio.to_thread`.
4. **The database owns the tracked set:** the watchlist plus every ticker with an open position. Callers pass it to `source.sync_tickers()`.
5. **Background tasks never die.** Every error is logged and retried, and the cache keeps the last good prices meanwhile.

### Modules

| File                          | Responsibility                                                                                                   |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `services/market/models.py`   | `PriceUpdate`, a frozen dataclass: price, previous price, previous close, timestamp; derived change, day change % and direction |
| `services/market/cache.py`    | `PriceCache`: latest price per ticker, a `version` counter and `wait_for_change()` for push-on-change readers. Validates and rounds prices |
| `services/market/tickers.py`  | `normalize_ticker()`: upper-cases and validates symbols (`aapl` → `AAPL`, `brk.b` → `BRK.B`), raising `ValueError` |
| `services/market/base.py`     | `MarketDataSource`, the abstract interface, with a default `sync_tickers()`                                      |
| `services/market/factory.py`  | `create_market_data_source()`: picks the source from the env vars                                                 |
| `services/market/simulator.py`| `GBMSimulator` (pure math) and `SimulatorDataSource` (asyncio wrapper)                                            |
| `services/market/massive.py`  | `MassiveDataSource`: snapshot polling, automatic end-of-day fallback on the free plan, backoff                    |
| `routes/stream.py`            | `GET /api/stream/prices`                                                                                         |
| `dependencies.py`             | `PriceCacheDep`, `MarketSourceDep` for route signatures                                                           |
| `main.py`                     | Lifespan (creates, starts and stops the source), `/api/health`, logging setup                                     |

## 4. Using It from Other Backend Code

Import everything from `app.services.market`. Only the factory and the tests import the concrete sources.

```python
from app.dependencies import MarketSourceDep, PriceCacheDep
from app.services.market import MarketDataSource, PriceCache, PriceUpdate, normalize_ticker
```

| Call                                   | Use                                                                                                                  |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `cache.get_price(t) -> float \| None`  | Fill price for trades, and portfolio valuation. **Can be `None`**: an unknown ticker on Massive, or Massive unreachable since startup |
| `cache.get(t) -> PriceUpdate \| None`  | Full quote for the watchlist and the LLM context; `.to_dict()` gives the SSE/REST shape                               |
| `await source.sync_tickers(tickers)`   | After any watchlist change or trade: makes the tracked set exactly `watchlist ∪ open positions`. Idempotent           |
| `await source.add_ticker(t)`           | Before reading a fill price for a ticker that may not be tracked yet. Prices it right away where possible             |
| `normalize_ticker(raw)`                | On every ticker that comes in from outside: request bodies, path parameters, LLM output. Answer `ValueError` with 422 |
| `source.status()`                      | Diagnostics for `/api/health`                                                                                        |

Contract details:

- **A trade on a ticker with no price** is rejected with 400 (or reported as an error in the chat reply). **Valuation without a price** falls back to the position's average cost.
- **`add_ticker` behaves differently by source.** The simulator always prices the ticker immediately. Massive in snapshot mode makes one call and waits **at most 3 seconds**; a slower call finishes in the background. While the API is failing, Massive makes no call and the background poll prices the ticker on recovery. Massive in EOD mode serves stored closes, with no call.
- **`sync_tickers` on Massive** prices all new tickers in a single snapshot call.
- Design §11.6 has worked sketches of the watchlist routes, trade execution, valuation and LLM context code.

## 5. SSE Contract (for the Frontend)

`GET /api/stream/prices`: an unnamed `message` event, so use `EventSource.onmessage`. Each event carries the **full current state of every tracked ticker**, keyed by ticker. A ticker missing from an event has been removed.

```
retry: 1000
data: {"AAPL": {"ticker": "AAPL", "price": 189.91, "previous_price": 190.0, "prev_close": 190.0, "change": -0.09, "day_change_percent": -0.0474, "direction": "down", "timestamp": 1791346929.611}, ...}
```

```ts
interface PriceUpdate {
  ticker: string;
  price: number;              // cents, or 4 decimals below $1
  previous_price: number;     // price from the previous update
  prev_close: number;         // base for day_change_percent
  change: number;             // price - previous_price
  day_change_percent: number; // 4 decimals
  direction: "up" | "down" | "flat";
  timestamp: number;          // Unix seconds the server received it
}
```

- **Timing:** the first event arrives as soon as the client connects. After that, an event goes out on every cache change: about every 0.5s with the simulator, once per poll with Massive.
- **Reconnects:** `retry: 1000` makes the browser reconnect after 1s. A `: ping` comment arrives after 15s without events (FastAPI's built-in keepalive).
- **Flashes:** flash on the difference from the **last rendered price**, not on `direction`. A slow client may not have rendered every update.
- **The payload is always valid JSON.** The cache rejects NaN and infinite prices and never stores an unusable `prev_close`.

## 6. The Price Sources

### 6.1 Simulator (Default)

- **GBM** in log space: `S ← S·exp((μ − σ²/2)·dt + σ·√dt·Z)`.
- **Compressed clock:** each 0.5s tick carries 20 trading-seconds of volatility, so prices move visibly.
- **Correlation from a factor model:** `Z = √0.3·market + √0.3·sector + √0.4·own`. Same sector correlates at 0.6, different sectors at 0.3. Measured on 20k ticks: AAPL–MSFT 0.60, AAPL–JPM 0.30.
- **Jumps:** a 0.0005 chance per ticker per tick of a ±2–5% move, about one every 100s across ten tickers.
- **Profiles:** AAPL 190, GOOGL 175, MSFT 420, AMZN 185, NVDA 130 and META 500 are tech; TSLA 250 is auto, NFLX 650 media, JPM 200 and V 280 finance. σ ranges from 0.20 (V) to 0.60 (TSLA). Any other ticker gets σ 0.30 and a stable seed of $50–$300 from `crc32(ticker)`, in its own sector.
- **`prev_close` is the seed price**, so the day change means "since the simulated open". A removed ticker parks its last price and resumes from it when re-added.
- **Tunable** through `GBMSimulator(...)` arguments. Seed it with `rng=random.Random(n)` for reproducible runs.

### 6.2 Massive API (When `MASSIVE_API_KEY` Is Set)

| Mode                            | Plans        | Data                                           | Calls                                                    |
| ------------------------------- | ------------ | ---------------------------------------------- | -------------------------------------------------------- |
| Snapshot                        | Starter and up | Full Market Snapshot, every `MASSIVE_POLL_SECONDS` (15). 15-minute delayed on Starter and Developer | 1 per poll for any number of tickers; 1 per batch of adds |
| End of day (EOD)                | Free         | Grouped daily closes from the last two sessions, refreshed hourly | ≤ 5 at startup (the free plan's per-minute limit), 2–4 per hour, 0 per add |

- **Plan detection is automatic.** The first `403 NOT_AUTHORIZED` from the snapshot endpoint switches to EOD mode for the rest of the process, so a downgrade is handled live. An upgrade needs a restart.
- **The EOD walk** starts at yesterday (New York, approximated as UTC−5, never ahead of the real date). It skips weekends without a call, passes over holidays and 403 days, and stops after 4 lookups.
- **Failures** (bad key, rate limit, network, 5xx, unexpected payloads) are logged and retried with backoff of `poll × 2^n`, capped at 5 minutes and at least 60s apart in EOD mode. `/api/health` shows `last_error` until the next success.
- **Safety details:**
  - The client is built with `retries=0` and 5s/10s timeouts. With its own retries, one 429 blocked for 6s and sent 4 requests.
  - Refreshes are serialized by a lock.
  - Poll results for tickers removed while the request was in flight are discarded.

## 7. Configuration and Running

| Env var                | Default | Effect                                                                                     |
| ---------------------- | ------- | ------------------------------------------------------------------------------------------ |
| `MASSIVE_API_KEY`      | empty   | Non-empty → Massive. Empty or whitespace → simulator                                         |
| `MASSIVE_POLL_SECONDS` | `15`    | Snapshot poll interval (≥ 1; bad values log a warning and fall back to 15). 2–5 suits paid plans |

```bash
cd backend
uv sync
uv run uvicorn app.main:app --port 8000 --timeout-graceful-shutdown 2
curl -N localhost:8000/api/stream/prices
curl localhost:8000/api/health    # {"status":"ok","market_data":{"source":"simulator","tickers":10}}
```

- **Always pass `--timeout-graceful-shutdown 2`.** SSE streams never end on their own. Without it, a shutdown waits for every open browser tab: `docker stop` ends in a forced kill and `--reload` stalls. PLAN.md §11 gives the exact Docker `CMD`.
- **Run a single uvicorn worker** (the default). The cache and the simulator live in process memory.
- `.env.example` documents both variables.

### 7.1 Terminal Demo

A live dashboard built with `rich` (a dev dependency). It runs the real `SimulatorDataSource` and `PriceCache`, and redraws on every cache change, the same way the SSE stream pushes to the browser.

```bash
cd backend
uv run python -m demos.market_simulator                                   # Ctrl+C to quit
uv run python -m demos.market_simulator --seed 42 --duration 60           # reproducible, timed
uv run python -m demos.market_simulator --tickers AAPL,NVDA,PYPL --jumps 0.005   # more jump events
```

- **Header:** live status, ticker and tick counts, tick rate, uptime, jump count, and breadth (advancers and decliners).
- **Prices table:** price with an up or down arrow colored by the last tick, the tick change, the day change %, a 40-tick sparkline, and the session high and low. A ticker that just jumped is highlighted for 3 seconds.
- **Sectors:** the average day change per sector, with a bar. Correlated sector moves are easy to see here.
- **Jump events:** a log of the ±2–5% moves.
- **Options:** `--tickers`, `--seed`, `--duration`, `--tick`, `--time-scale` and `--jumps` (the jump probability per ticker per tick). All are validated, and bad values give a clear error.
- **Output:** written to a pipe or file, it prints only the final frame.
- **Code:** `backend/demos/market_simulator.py`. The view logic is a pure `Dashboard` class, tested in `tests/demos/test_market_simulator.py`.

## 8. Testing

```bash
cd backend
uv run pytest                                   # 83 passed
uv run ruff check app tests demos && uv run ruff format --check app tests demos && uv run mypy app demos
```

| File                                       | Tests | Covers                                                                                                                                         |
| ------------------------------------------ | ----- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/services/market/test_cache.py`      | 15    | previous price and direction, rounding (4 decimals below $1, validated after rounding), `prev_close` carry-forward including unusable values, invalid prices, `version`, the SSE dict, `wait_for_change` |
| `tests/services/market/test_interface.py`  | 18    | `normalize_ticker`, factory selection, `MASSIVE_POLL_SECONDS` parsing, `sync_tickers`                                                           |
| `tests/services/market/test_simulator.py`  | 12    | profiles, seeded determinism, parked prices, volatility and correlations against the model, jump rate, start/add/remove/stop, a failing tick, idempotency |
| `tests/services/market/test_massive.py`    | 28    | no hidden retries, price fallback order, 403 detection, batching, add waits at most 3s and skips calls while failing, the in-flight removal race, the free-plan EOD fallback with exact call sequences, holidays, the lookup cap, backoff and recovery, downgrades (also with concurrent adds), `us_market_today()` |
| `tests/routes/test_stream.py`              | 2     | real uvicorn and httpx: headers, `retry`, full state on connect, an event per change, removed tickers dropping out, shutdown with a client attached |
| `tests/test_main.py`                       | 1     | lifespan starts the simulator, `/api/health`, the source stops on shutdown                                                                     |
| `tests/demos/test_market_simulator.py`     | 7     | terminal demo: sparkline scaling, jump detection, highlighting and fading, removed tickers, a timed run against the real simulator, argument validation |

The Massive tests use a `FakeClient` injected through the constructor. The statistical tests use fixed seeds, so they are deterministic.

### What Verified the Code Beyond the Unit Tests

- **Stability:** the suite passed every repeat run, on an idle machine and under heavy CPU load (16 busy loops on 8 cores).
- **Mutation spot-checks:** 11 deliberate bugs, applied one at a time, are now **all caught**. Before the review fixes, 7 were caught.
- **Live server:** startup, `/api/health`, the stream under `curl -N`, and SIGTERM with a client attached (exits in 2.2s, and the lifespan shutdown runs).
- **Massive over real HTTP:** the real `RESTClient` against a local fake server.
  - Starter plan: 1 call.
  - Free plan: 3 calls, switched to EOD mode, correct closes.
  - Bad key, 429 and 500: 1 call each, no crash, with `last_error` set.
- **Stream fan-out:** 5 clients each received every event, and 0 cache waiters remained after they disconnected.
- **Latency and budget:** adding 2 tickers while Massive hangs takes 3.0s (was 20.0s). A plan downgrade with concurrent adds takes 5 calls (was 7).
- **No Massive key was available**, so the live 403 wording for the free plan is still unverified. Detection is deliberately lenient (§9).

## 9. Review Outcome

[MARKET_DATA_REVIEW.md](archive/MARKET_DATA_REVIEW.md) (archived) has the full findings and evidence. Design §16 summarizes the changes.

| Finding                                                              | Resolution (PR #8)                                                      |
| -------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| M1: shutdown hung while any browser held the stream open             | `--timeout-graceful-shutdown 2` in the run command; regression test     |
| M2: Massive `add_ticker` could block a request for 10s per ticker    | One batched call, a 3s maximum wait, no call while failing              |
| L1: a sub-cent price became 0.0; a NaN `prev_close` broke the SSE JSON | Round first, then validate; unusable `prev_close` carries forward     |
| L2: a downgrade with concurrent adds could exceed the free plan's 5 calls/min | `asyncio.Lock` around refreshes                                  |
| L3: the app's INFO logs never appeared                               | Logging configured in `main.py`                                         |
| L4: `tracked_tickers()` is a placeholder                             | **Open**: belongs to the database layer (§10)                           |
| T1–T6: untested behaviours                                           | 19 new tests                                                            |
| N1–N4: tooling and doc drift                                         | ruff and mypy configured; docs updated; the code declared the source of truth |

## 10. Known Limitations and Open Items

| Item                                               | Impact and what to do                                                                                                       |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **`tracked_tickers()` in `main.py` is a placeholder** | Returns the ten default tickers. The database agent must replace it with `watchlist ∪ open positions` and call `sync_tickers` / `add_ticker` from the watchlist routes, trade execution and the chat flow (design §11.5–11.6) |
| Simulator restarts from seed prices                 | Held positions can show a P&L jump after a restart. Later: give `GBMSimulator.add()` a starting price from the last trade     |
| Free Massive plan gives static prices               | EOD closes only, so no flashes and flat sparklines. Leave `MASSIVE_API_KEY` empty for a lively demo                            |
| Starter and Developer data is 15 minutes delayed    | Consider a "delayed" badge when `/api/health` reports `"source": "massive"`                                                  |
| No market-hours logic                               | The simulator moves 24/7. Massive keeps polling while markets are closed                                                      |
| EOD mode is sticky                                  | Restart after upgrading the Massive plan                                                                                     |
| Single process                                      | Run one uvicorn worker                                                                                                       |
| Free-plan 403 wording unverified                    | Check `/api/health` shows `"mode": "eod"` the first time a free key is used                                                   |

## 11. Handoff Checklist for Other Agents

- **Backend / database:**
  - Implement `tracked_tickers()`.
  - Call `sync_tickers` after watchlist changes and trades, and `add_ticker` before reading a fill price.
  - Normalize every incoming ticker.
  - Treat a `None` price as "no price".
- **Docker / scripts:** use the `CMD` from PLAN.md §11, including `--timeout-graceful-shutdown 2`, with a single worker.
- **Frontend:** follow §5. Use `onmessage`, flash against the last rendered price, and drop tickers missing from an event. Drive the connection dot from `onopen` / `onerror` and `readyState`.
- **LLM / chat:** watchlist changes and trades go through the same `sync_tickers` and trade paths, so "add PYPL and buy 10" works on every source.

## 12. Document Map

| Document                                                      | Status                                                                                       |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| **MARKET_DATA_SUMMARY.md** (this file)                        | Current overview and handoff, including the contracts other agents rely on                   |
| `backend/CLAUDE.md`                                           | Developer guide for backend work: setup, commands, conventions, key APIs                     |
| [MARKET_DATA_DESIGN.md](MARKET_DATA_DESIGN.md)                | Current design: intent, contracts, rationale. It names the files to read rather than copying code; **the code in `backend/` is the source of truth** |
| [archive/MARKET_DATA_REVIEW.md](archive/MARKET_DATA_REVIEW.md) | Archived: code review findings, evidence and resolution (complete)                           |
| [MASSIVE_API.md](MASSIVE_API.md)                              | Massive API reference: plans, endpoints, client behaviour                                     |
| [archive/MARKET_INTERFACE.md](archive/MARKET_INTERFACE.md)     | Superseded first draft of the interface                                                      |
| [archive/MARKET_SIMULATOR.md](archive/MARKET_SIMULATOR.md)     | Superseded first draft of the simulator; its model derivations still hold                    |

**Development note (Sprite VM only):** the `/.sprite` pyenv shims hang, so uv is set up with `python-preference = "only-managed"` in `~/.config/uv/uv.toml`. Inside `backend/`, use `.venv/bin/python` rather than bare `python3`. Docker and other machines are unaffected.
