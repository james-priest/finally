# Market Data Backend: Detailed Design

The implementation spec for FinAlly's market data subsystem (PLAN.md §6): one interface, two price sources (a GBM simulator and the Massive REST API), one shared price cache, and the SSE stream that pushes prices to the browser. It explains the design, the contracts the rest of the backend relies on, and the reasons behind them. The code itself lives in `backend/`.

**How it relates to the other planning docs.** This document merges [MARKET_INTERFACE.md](archive/MARKET_INTERFACE.md) and [MARKET_SIMULATOR.md](archive/MARKET_SIMULATOR.md) (both now archived) into one buildable design and **supersedes their code where they differ**. §14 lists every change and why. [MASSIVE_API.md](MASSIVE_API.md) remains the reference for Massive endpoints, plans and the Python client, and MARKET_SIMULATOR.md for the simulator's derivations.

**Status: implemented. The code in `backend/` is the source of truth.** This document keeps the design: intent, contracts and the reasons behind them. It no longer carries the code; each section names the file to read. [MARKET_DATA_SUMMARY.md](MARKET_DATA_SUMMARY.md) is the current overview and handoff, and `backend/CLAUDE.md` is the developer guide. The code review ([MARKET_DATA_REVIEW.md](archive/MARKET_DATA_REVIEW.md), archived) led to the changes in §16.

**Verification history.** Before implementation, every line of code in this design was run on Python 3.12 with FastAPI 0.142.2 and massive 2.8.0:

- 57 tests passed with no network or API key, and each fix in §14 (F1–F6) was mutation-checked.
- The Massive source was driven through the real `RESTClient` against a fake server.
- The SSE endpoint was checked under uvicorn with curl.

The implementation then went through the review and fixes in §16, and now has 83 tests.

Contents: 1 Requirements · 2 Architecture · 3 Module layout · 4 Data model · 5 Price cache · 6 Ticker symbols · 7 Interface · 8 Factory · 9 Simulator · 10 Massive source · 11 FastAPI integration · 12 Testing · 13 Implementation checklist · 14 Changes from the earlier drafts · 15 Known limitations · 16 Changes after the code review

## 1. Requirements

| #   | Requirement (source)                                                                                                                    | Met by                                     |
| --- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| R1  | One interface, two implementations. `MASSIVE_API_KEY` set and non-empty → Massive, otherwise the simulator (PLAN §5, §6)                | `MarketDataSource`, factory (§7, §8)       |
| R2  | Simulator: GBM, ~500ms updates, correlated moves, occasional 2–5% events, realistic seed prices, in-process, no dependencies (PLAN §6)  | `GBMSimulator`, `SimulatorDataSource` (§9) |
| R3  | Massive: REST polling (not WebSocket) for the union of watched tickers, 15s by default (PLAN §6)                                        | `MassiveDataSource`, snapshot mode (§10)   |
| R4  | Works on the free Massive plan: 5 calls/min and no snapshot endpoint (MASSIVE_API.md §3)                                                | EOD mode (§10.2)                           |
| R5  | One in-memory cache with latest price, previous price and timestamp per ticker; a single writer (PLAN §6)                               | `PriceCache` (§5)                          |
| R6  | `GET /api/stream/prices`: SSE at ~500ms with ticker, price, previous price, timestamp and direction; `EventSource` reconnects (PLAN §6) | `routes/stream.py` (§11.3, §11.4)          |
| R7  | Prices for trade fills, portfolio value, the 30s snapshots, `GET /api/watchlist` and the LLM's context (PLAN §7–§9)                     | `PriceCache.get` / `get_price` (§11.6)     |
| R8  | Tickers added and removed at runtime by REST or chat; a new ticker is priced right away; held tickers stay priced                       | `add_ticker`, `sync_tickers` (§7, §11.5)   |
| R9  | Unit tests: GBM math, Massive parsing, both sources honor the interface (PLAN §12)                                                      | `backend/tests/` (§12)                    |

## 2. Architecture

```
                         ┌──────────────────────────────┐
  MASSIVE_API_KEY? ───►  │ create_market_data_source()  │
                         └──────────────┬───────────────┘
                   ┌────────────────────┴────────────────────┐
                   ▼                                         ▼
        SimulatorDataSource                        MassiveDataSource
        asyncio task, tick every 0.5s              asyncio task: snapshot poll every 15s,
        GBMSimulator does the math                 or hourly EOD on the free plan; HTTP in a thread
                   └────────────────────┬────────────────────┘
                                        ▼  cache.update(ticker, price, prev_close)
                                 ┌────────────┐
                                 │ PriceCache │  latest PriceUpdate per ticker + version counter
                                 └─────┬──────┘
          ┌────────────────────────────┼───────────────────────────────┐
          ▼                            ▼                               ▼
  GET /api/stream/prices       trade execution                 portfolio value, snapshots,
  await wait_for_change(),     fills at the cache price        GET /api/watchlist, LLM context
  then push the full state

  watchlist or position changed ──► source.sync_tickers(watchlist ∪ open positions)
```

Rules:

1. **One writer, many readers.** Only the active source writes to the cache.
2. **Nothing outside `services/market/` knows which source is running.** Code reads prices from `PriceCache` and changes the tracked set through `MarketDataSource`. The one exception is `status()`, reported by `/api/health` for diagnostics.
3. **Everything runs on the event loop thread.** The Massive client is synchronous, so its HTTP calls run in `asyncio.to_thread`. The cache is written only after control returns to the loop, so it needs no lock.
4. **The database owns the tracked set:** the watchlist plus every ticker with an open position. After either changes, the caller hands the new set to `source.sync_tickers()`.
5. **Background tasks never die.** Every failure is logged and retried, and the cache keeps the last good prices meanwhile.

## 3. Module Layout and Dependencies

`app` is the backend's Python package. Market data is service-layer code with its own package. The lifespan, a dependencies module and the SSE route wire it into the app. Other services only read the cache and call `add_ticker` / `sync_tickers` (§11.6).

```
backend/
  CLAUDE.md                  # developer guide: setup, commands, conventions
  pyproject.toml             # dependencies; pytest, ruff and mypy settings
  app/
    main.py                  # lifespan creates, starts and stops the source; /api/health (§11.1)
    dependencies.py          # PriceCacheDep, MarketSourceDep (§11.2)
    routes/stream.py         # GET /api/stream/prices (§11.3)
    services/market/
      __init__.py            # public API
      models.py              # PriceUpdate (§4)
      cache.py               # PriceCache, round_price (§5)
      tickers.py             # normalize_ticker (§6)
      base.py                # MarketDataSource (§7)
      factory.py             # create_market_data_source (§8)
      simulator.py           # GBMSimulator, SimulatorDataSource (§9)
      massive.py             # MassiveDataSource (§10)
  demos/market_simulator.py  # live terminal dashboard (rich)
  tests/
    services/market/         # test_cache, test_interface, test_simulator, test_massive
    routes/test_stream.py
    test_main.py
    demos/test_market_simulator.py
```

Dependencies and tool settings (pytest's `asyncio_mode = "auto"`, ruff, mypy) are in `backend/pyproject.toml`. FastAPI must be 0.135 or later for `fastapi.sse`. `rich` is a dev dependency used only by the demo.

The package's public API, importable from `app.services.market`: `MarketDataSource`, `PriceCache`, `PriceUpdate`, `create_market_data_source` and `normalize_ticker`.

Everything outside the package imports from `app.services.market`. Only the factory and the tests import `SimulatorDataSource` or `MassiveDataSource` directly.

## 4. Data Model — `models.py`

`PriceUpdate` is the one price record. It is stored in the cache, read by services, and serialized for SSE and REST.

The code is in `backend/app/services/market/models.py`. In `to_dict()`, `change` and `day_change_percent` are rounded to 4 decimals and `timestamp` to milliseconds. `direction` is typed as `Literal["up", "down", "flat"]`.

| Field                | Meaning                                                                                                                                                     |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `price`              | Latest price, rounded to cents (4 decimals below $1)                                                                                                        |
| `previous_price`     | Price from the previous update (tick or poll). Drives `change` and `direction`.                                                                             |
| `prev_close`         | Base for the daily change. Massive snapshot: previous session's close. Massive EOD: close of the session before. Simulator: the ticker's seed price.        |
| `timestamp`          | Unix seconds when the cache received the update. Not the exchange time: Massive data can be 15 minutes old, and receive time keeps charts on a live x-axis. |
| `change`             | `price − previous_price`                                                                                                                                    |
| `day_change_percent` | `(price − prev_close) / prev_close × 100`, 4 decimals (0 if `prev_close` is 0)                                                                              |
| `direction`          | `"up"`, `"down"` or `"flat"` compared with `previous_price`                                                                                                 |

## 5. Price Cache — `cache.py`

The code is in `backend/app/services/market/cache.py`, which also exports `round_price()`.

- **`update()`** rounds to cents (4 decimals below $1, so sub-dollar stocks keep their precision) and makes the old price the new `previous_price`. When `prev_close` is not given, or is unusable (zero, negative, NaN, infinity), the stored one carries forward (the first update uses its own price).
- **Invalid prices raise `ValueError`** (zero, negative, NaN, infinity), checked **after** rounding, so a positive price that rounds to 0 is rejected too. Neither source produces them in normal operation, but one NaN would serialize as `NaN`, which `JSON.parse` rejects, breaking the stream for every client.
- **`version`** goes up on every change. `wait_for_change(v)` returns as soon as `version != v`. Each change sets the current `asyncio.Event`, waking every waiter, and swaps in a fresh one. Setting an event is synchronous, so `update()` stays a plain method that sources can call in a loop. Waiters only run once the writer yields, so a simulator tick that updates ten tickers wakes the SSE stream once, after the whole tick.

## 6. Ticker Symbols — `tickers.py`

`normalize_ticker()` in `backend/app/services/market/tickers.py` strips and upper-cases its input. It then requires 1–7 letters or digits starting with a letter, plus an optional `.` or `-` share-class suffix of 1–3 characters (`AAPL`, `V`, `BRK.B`, `BF-B`). Anything else raises `ValueError`.

Call `normalize_ticker` wherever a ticker enters from outside: request bodies, path parameters, and tickers in the LLM's structured output. Answer `ValueError` with HTTP 422 (§11.6). The sources assume normalized input. Massive tickers are case-sensitive (`aapl` matches nothing), and without this check the simulator would invent a price for `HELLO WORLD`.

## 7. The Interface — `base.py`

The code is in `backend/app/services/market/base.py`. Tickers passed in must already be normalized (§6).

| Method                        | Contract                                                                                                                                                    |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `async start(tickers)`        | Price the given tickers, then keep them updated from a background task. When it returns, every ticker that can be priced is in the cache. A second call does not start a second task |
| `async stop()`                | Cancel the background work. Safe to call more than once                                                                                                     |
| `async add_ticker(ticker)`    | Start tracking a ticker and price it right away if possible. No-op if already tracked                                                                       |
| `async remove_ticker(ticker)` | Stop tracking a ticker and drop it from the cache. No-op if not tracked                                                                                      |
| `get_tickers() -> list[str]`  | Tracked tickers, sorted                                                                                                                                     |
| `async sync_tickers(tickers)` | Make the tracked set exactly `tickers`: remove the extras, then add what is missing. `MassiveDataSource` overrides it to price all new tickers in one call |
| `status() -> dict`            | Small JSON-friendly summary for `/api/health`                                                                                                               |

How each implementation behaves:

|                             | Simulator                                             | Massive, snapshot mode (Starter plan and up) | Massive, EOD mode (free plan)            |
| --------------------------- | ----------------------------------------------------- | -------------------------------------------- | ---------------------------------------- |
| Updates                     | every 0.5s                                            | every `MASSIVE_POLL_SECONDS` (15)            | hourly; the data changes once a day      |
| When `start()` returns      | every ticker priced (seed price)                      | priced from the first poll                   | priced from the latest EOD data          |
| When `add_ticker()` returns | priced (seed price, or its last price if seen before) | priced, unless the call takes over 3s or the API is failing (then the background poll prices it) | priced from stored EOD data, no API call |
| `prev_close`                | seed price                                            | previous session's close (`prevDay.c`)       | close of the session before              |
| Unknown ticker              | gets a generated price                                | never priced                                 | never priced                             |
| API calls                   | none                                                  | 1 per poll, 1 per `add_ticker` or `sync_tickers` that adds tickers | ≤ 5 at startup, 2–4 per hour             |

Contract for callers:

- **Handle "no price".** `cache.get_price(t)` can be `None`: an unknown ticker on Massive, or Massive unreachable since startup. A trade on such a ticker is rejected with 400, and valuation falls back to cost (§11.6).
- **`add_ticker` and `remove_ticker` are coroutines**, because adding may fetch a price. Both are idempotent.
- **Prefer `sync_tickers(watchlist ∪ open positions)`** to pairing adds and removes by hand. It is idempotent, so a missed call is repaired by the next one.

## 8. Factory and Configuration — `factory.py`

The code is in `backend/app/services/market/factory.py`.

| Env var                | Default | Effect                                                                                                                                                                                                                                                                                           |
| ---------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `MASSIVE_API_KEY`      | empty   | Non-empty → Massive; empty or whitespace → simulator                                                                                                                                                                                                                                             |
| `MASSIVE_POLL_SECONDS` | `15`    | Snapshot poll interval, at least 1, and the base of the retry backoff. Starter plans and up have unlimited calls, so 2–5 is fine. EOD mode refreshes hourly and retries at most once a minute, so a low value left over after a downgrade is safe. Bad values log a warning and fall back to 15. |

Add `MASSIVE_POLL_SECONDS=` to `.env.example` as optional. The factory reads `os.environ` when it runs, so `.env` must already be loaded: Docker's `--env-file` does this; locally, use `uv run --env-file ../.env ...`.

## 9. Simulator — `simulator.py`

### 9.1 Model

The math is unchanged from [MARKET_SIMULATOR.md](archive/MARKET_SIMULATOR.md) (archived), which has the derivations.

- **GBM step**, every tick: `S ← S · exp((μ − σ²/2)·dt + σ·√dt·Z)`. Working in log space keeps prices positive.
- **Correlation from a factor model:** `Z_i = √0.3·M + √0.3·S_sector(i) + √0.4·ε_i`, with independent `N(0,1)` draws for the market, each sector and each ticker. Tickers in the same sector correlate at 0.6, others at 0.3. Adding a ticker needs no matrix rebuild, and a tick costs O(n).
- **Jump events:** each ticker, each tick, has a 0.0005 chance of an extra ±2–5% move. That is about one event every 100s across ten tickers.
- **Compressed clock:** each 0.5s tick carries 20 trading-seconds of volatility (`dt = 0.5 × 20 / 5,896,800 ≈ 1.7e-6` years). At real-time volatility most ticks would not move the price by a cent.

Re-measured on this implementation (seed 42, 20,000 ticks; jump events off for the volatility columns):

| Ticker | σ    | Per tick | 1 min | 1 hour | Ticks with no visible change |
| ------ | ---- | -------- | ----- | ------ | ---------------------------- |
| V      | 0.20 | 0.026%   | 0.29% | 2.2%   | 5.5%                         |
| AAPL   | 0.25 | 0.033%   | 0.36% | 2.8%   | 6.7%                         |
| NVDA   | 0.50 | 0.065%   | 0.71% | 5.5%   | 5.2%                         |
| TSLA   | 0.60 | 0.078%   | 0.85% | 6.6%   | 1.9%                         |

Measured correlations: AAPL–MSFT 0.60, NVDA–META 0.60, JPM–V 0.60, AAPL–JPM 0.30, TSLA–NFLX 0.30, and AAPL against an unknown ticker (PYPL) 0.30. With the default settings and ten tickers, a jump event happened every 104s.

### 9.2 Ticker Profiles

| Ticker | Seed | σ    | μ    | Sector  |
| ------ | ---- | ---- | ---- | ------- |
| AAPL   | 190  | 0.25 | 0.08 | tech    |
| GOOGL  | 175  | 0.30 | 0.08 | tech    |
| MSFT   | 420  | 0.25 | 0.08 | tech    |
| AMZN   | 185  | 0.32 | 0.08 | tech    |
| NVDA   | 130  | 0.50 | 0.12 | tech    |
| META   | 500  | 0.40 | 0.08 | tech    |
| TSLA   | 250  | 0.60 | 0.05 | auto    |
| NFLX   | 650  | 0.40 | 0.08 | media   |
| JPM    | 200  | 0.22 | 0.06 | finance |
| V      | 280  | 0.20 | 0.06 | finance |

Any other ticker gets σ 0.30 and μ 0.08 and is its own sector, so it moves with the market only. Its seed price is `50 + crc32(ticker) % 25000 / 100`, between $50 and $300 and the same on every run (unlike `hash()`, `crc32` is not randomized per process). Seed prices are illustrative, not current quotes.

### 9.3 Implementation

`GBMSimulator` does the math with no asyncio or I/O, so it is easy to test. `SimulatorDataSource` wraps it in a background task and implements `MarketDataSource`.

The code is in `backend/app/services/market/simulator.py`. `PROFILES` holds the table in §9.2, and `profile_for()` builds the default profile for any other ticker. `GBMSimulator` caches each ticker's profile when it is added, keeps unrounded prices, and parks a removed ticker's last price. `SimulatorDataSource.start()` prices every ticker before the first tick, and its loop logs a failing tick and carries on.

### 9.4 Behavior Notes

- **Prices stay unrounded** inside the simulator, and the cache rounds for display. Rounding inside would bias small moves.
- **`add_ticker` writes a price at once**, so a new ticker can be traded before the next tick.
- **`prev_close` is always the seed price**, so `day_change_percent` means "since the simulated open", even across a remove and re-add.
- **A removed ticker's last price is parked.** Re-adding resumes from it rather than jumping back to the seed.
- **A tick is synchronous:** there is no `await` inside `step()` or the write loop, so readers never see half a tick.
- **A failing tick is logged** with its traceback, and the loop carries on.

### 9.5 Tuning Knobs

These are `GBMSimulator` constructor arguments. There are no env vars for them; add one only if a real need appears.

| Parameter           | Default  | Effect                                                                            |
| ------------------- | -------- | --------------------------------------------------------------------------------- |
| `tick_seconds`      | 0.5      | Real time between ticks. `SimulatorDataSource(tick_seconds=...)` passes it on.    |
| `time_scale`        | 20       | Trading-seconds of volatility per real second. Volatility grows with √time_scale. |
| `market_weight`     | 0.3      | Share of variance from the market factor                                          |
| `sector_weight`     | 0.3      | Share of variance from the sector factor                                          |
| `event_probability` | 0.0005   | Jump chance per ticker per tick                                                   |
| `rng`               | unseeded | `random.Random(seed)` for reproducible runs                                       |

## 10. Massive Source — `massive.py`

### 10.1 Plans and Endpoints

MASSIVE_API.md has the details. Two facts shape the design:

- The **Full Market Snapshot** (`GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,...`) prices every tracked ticker in one call, but only on Starter ($29/month) and up. On Starter and Developer the data is 15 minutes delayed.
- The **free Basic plan** (5 calls/min) has no snapshot or last-trade access. The best it offers is end-of-day closes from the **grouped daily** endpoint (`GET /v2/aggs/grouped/locale/us/market/stocks/{date}`), which covers every US stock in one call.

### 10.2 Modes and Request Budget

The source starts in **snapshot mode**. The first `403 NOT_AUTHORIZED` from the snapshot endpoint switches it to **EOD mode** for the rest of the process, so restart after upgrading the plan.

The EOD refresh walks back from **yesterday** in New York, one day at a time. Saturdays and Sundays are skipped without a call. A holiday (empty response) or a day the plan cannot see yet (403) is passed over. The walk stops once it has two sessions or after `MAX_EOD_LOOKUPS = 4` calls. The newest session gives `price`; the one before gives `prev_close`. If only one session is found, `prev_close = price`.

| Situation                   | API calls                                                                                                     |
| --------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Snapshot mode, each poll    | 1, for any number of tickers                                                                                  |
| Snapshot mode, `add_ticker` | 1                                                                                                             |
| EOD mode, startup           | 1 snapshot probe (403), then 2 grouped calls (up to 4 after a holiday): ≤ 5, the free plan's per-minute limit |
| EOD mode, hourly refresh    | 2–4                                                                                                           |
| EOD mode, `add_ticker`      | 0, served from the stored closes for all US stocks                                                            |

### 10.3 Implementation

The code is in `backend/app/services/market/massive.py`:

- **`snapshot_price(snap)`** picks a price using the fallback order in §10.5.
- **`is_not_authorized(error)`** is true for a 403 body with `"status": "NOT_AUTHORIZED"` or a "not entitled" message, and false for anything else, including bodies that aren't JSON.
- **`us_market_today()`** gives today's date in New York, approximated as UTC−5.
- **`MassiveDataSource`** does the polling:
  - Constants at the top of the module set the budget: `EOD_POLL_SECONDS`, `EOD_MIN_RETRY_SECONDS`, `MAX_BACKOFF_SECONDS`, `MAX_EOD_LOOKUPS` and `ADD_WAIT_SECONDS`.
  - `_refresh()` polls once under a lock and never raises. `_poll_snapshot()` and `_poll_eod()` handle the two modes, and `_recent_closes()` is the EOD walk, run in a thread.
  - `_record_success()` and `_record_failure()` keep the backoff state and the `status()` fields.
  - The constructor takes `client=` so tests can pass a fake (`FakeClient` in `tests/services/market/test_massive.py`).

### 10.4 Failure Handling

| Failure                                      | Seen as                                                   | Behavior                                             |
| -------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------- |
| Plan has no snapshot access                  | `BadResponse`, HTTP 403, `"status": "NOT_AUTHORIZED"`     | Switch to EOD mode and load EOD prices at once       |
| Bad key                                      | `BadResponse`, HTTP 401, `"error": "Unknown API Key"`     | Logged, retried with backoff, shown in `/api/health` |
| Rate limit (free plan)                       | `MaxRetryError` (429 with `retries=0`)                    | Logged, retried with backoff                         |
| Network down, timeout, HTTP 5xx              | `MaxRetryError` or another `urllib3.exceptions.HTTPError` | Logged, retried with backoff                         |
| No EOD data within 4 lookups                 | `EndOfDayDataMissing`                                     | Logged, retried with backoff                         |
| Anything else (a bug, an unexpected payload) | any other `Exception`                                     | Logged with traceback, retried with backoff          |

Backoff is `poll_seconds × 2^failures`, capped at 5 minutes: 30s, 60s, 120s, 240s, then 300s with the default 15s. In EOD mode retries are also at least 60s apart, because the free plan allows 5 calls a minute: a `MASSIVE_POLL_SECONDS` of 2 kept from a paid plan would otherwise retry after 4s, 8s and 16s. The first success resets the backoff and logs a recovery line. The cache keeps the last good prices throughout. On shutdown, `CancelledError` is not an `Exception`, so it passes straight through.

### 10.5 Design Notes

- **`retries=0` on the client.** Its built-in retry treats 429 as retryable and honors `Retry-After`, which urllib3 allows up to 6 hours. Measured against a fake server answering 429 with `Retry-After: 2`, the default `retries=3` blocked for 6.0s and sent 4 requests, while `retries=0` failed after 0.0s and 1 request. On the free plan, hidden retries would also spend the 5 calls/min budget. The poll loop is the only retry policy.
- **Timeouts of 5s to connect and 10s to read** bound each poll, and the wait in `start()`, when Massive is unreachable. Cancelling a `to_thread` call does not stop its thread: a hung request finishes in the background within the timeout.
- **Removed while in flight.** A poll takes the ticker list and then waits on HTTP in a thread. If a ticker is removed meanwhile, the response still contains it, so `_poll_snapshot` writes only tickers that are still tracked. Without that check, the removed ticker comes back into the cache and stays in every SSE event with a frozen price.
- **Why the walk starts at yesterday.** On the free plan a day's data only appears after the close. Whether Massive answers a same-day request with an empty result or a 403 could not be checked without a free key, so the walk skips today and also treats a 403 for any single day as "not available". The cost is that a new close appears at the first hourly refresh after midnight New York time, not right after the market closes.
- **`us_market_today()`** approximates New York as UTC−5. That is never ahead of the real date (daylight time is UTC−4), and the walk only needs "not in the future", so the slim Docker image needs no time zone database.
- **The key is passed explicitly** to `RESTClient`. The client's default reads the env var at import time, possibly before `.env` is loaded.
- **New tickers never hold up a request for long.** `add_ticker` and `sync_tickers` price new tickers with one snapshot call between them and wait at most `ADD_WAIT_SECONDS` (3s) for it. A slower call finishes in the background and writes its prices when it returns. While the API is failing (`_failures > 0`) no call is made at all, and the background poll prices the tickers once the API recovers.
- **One refresh at a time.** An `asyncio.Lock` serializes `_refresh`, so a background poll and an `add_ticker` never make overlapping calls, and a plan downgrade switches to EOD mode exactly once. A targeted refresh that finds EOD mode already on when it gets the lock serves its tickers from the stored closes, without a call.
- **Snapshot price fallback order:** last trade, minute bar close, day bar close, previous close. Starter has no last trade, and bars are reset overnight, so early-morning polls fall back to `prevDay.c`.

### 10.6 Switching Plans

No setting describes the plan. The source works it out from Massive's responses, so `.env` cannot disagree with the real subscription.

| Change                     | What happens                                                                                         | What to do                                                                                                                                                                                                                                               |
| -------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Downgrade to the free plan | The next snapshot poll gets `403 NOT_AUTHORIZED`, and the source switches to EOD mode while running. | Nothing. Check that `/api/health` shows `"mode": "eod"`; if it doesn't, the 403 wording differs from what `is_not_authorized` expects (§15). Consider removing `MASSIVE_API_KEY` to use the simulator, since the free plan only has static daily closes. |
| Upgrade to a paid plan     | EOD mode is sticky.                                                                                  | Restart the app. Optionally lower `MASSIVE_POLL_SECONDS` to 2–5.                                                                                                                                                                                         |

A plan variable would only add a way to be wrong. Set to "paid" on a free key, the snapshot calls still fail, so the fallback is needed anyway. Set to "free" on a paid key, the app would show static daily closes while you pay for live data.

`.env` on a paid plan, for example:

```bash
MASSIVE_API_KEY=your-key
MASSIVE_POLL_SECONDS=5
```

## 11. FastAPI Integration

### 11.1 Lifespan

The lifespan in `backend/app/main.py` creates the cache and, through the factory, the source. It awaits `source.start(tracked_tickers())`, stores both on `app.state`, and stops the source on shutdown. `tracked_tickers()` is a placeholder that returns the ten default tickers. When the database layer lands, the lifespan should first call `init_db()` (create tables and seed data if missing), and `tracked_tickers()` should return the watchlist plus open positions (§11.5).

Run a **single uvicorn worker** (the default). The cache and simulator live in process memory, so each extra worker would run its own simulator and show different prices.

Run uvicorn with **`--timeout-graceful-shutdown 2`**, for example `uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 2` as the Docker `CMD`. SSE streams never end on their own, and on SIGTERM uvicorn waits for open connections before it runs the lifespan shutdown, with no timeout by default. Without the flag, a shutdown with any browser tab open hangs until the tab closes: `docker stop` ends in SIGKILL after 10s and `--reload` stalls. With it, open streams are cancelled after 2s and the lifespan shutdown still runs. `test_graceful_shutdown_timeout_closes_open_streams` covers this.

`main.py` calls `logging.basicConfig(level=INFO)`. uvicorn configures only its own loggers, so without it the app's INFO lines (which source is running, polling recovered) never appear.

### 11.2 Dependencies — `dependencies.py`

`backend/app/dependencies.py` provides `PriceCacheDep` and `MarketSourceDep`: `Annotated` FastAPI dependencies that return `request.app.state.price_cache` and `request.app.state.market_source`. Use them in route signatures.

### 11.3 SSE Endpoint — `routes/stream.py`

The route is in `backend/app/routes/stream.py`. It is an async generator. It starts from version `-1`, so the first event goes out at once, then loops on `version = await cache.wait_for_change(version)` and yields a `ServerSentEvent` holding every ticker's `to_dict()`. The first event also carries `retry: 1000` (`RECONNECT_MS`).

FastAPI's native SSE support (`fastapi.sse`, FastAPI 0.135 and later) handles the details:

- writes the wire format;
- sets `Cache-Control: no-cache` and `X-Accel-Buffering: no`;
- sends a `: ping` comment after 15s without events, which stops proxies from closing a quiet Massive stream;
- cancels the generator when the client disconnects. Checked: one cache waiter per open stream, none after it closes.

**Why push on change instead of sampling the cache every 500ms** (as the earlier draft did):

- **Latency.** A sampling loop delivers each tick late by however far into the 500ms cycle the client happened to connect, and that delay is fixed for the life of the connection. Measured with clients connecting 0.05s, 0.25s and 0.45s after a tick: mean delays of 45ms, 261ms and 453ms. Push-on-change: 0.1ms.
- **Cadence follows the source:** two events a second with the simulator, one per poll with Massive, and one right away when a ticker is added. Nothing to retune if `tick_seconds` changes.
- **No ticks are skipped either way** at matching 500ms periods: both delivered 240 of 240 ticks over 120s. The two timers stay phase-locked, so this is an improvement, not a bug fix.

If a client reads slowly, the generator waits on the send and then sends the latest state, so a slow client gets merged updates instead of a growing backlog.

### 11.4 SSE Contract (for the Frontend)

Captured from the running prototype, trimmed to two tickers:

```
data: {"AAPL": {"ticker": "AAPL", "price": 190.0, "previous_price": 190.0, "prev_close": 190.0, "change": 0.0, "day_change_percent": 0.0, "direction": "flat", "timestamp": 1791346929.11}, "GOOGL": {...}, ...}
retry: 1000

data: {"AAPL": {"ticker": "AAPL", "price": 189.91, "previous_price": 190.0, "prev_close": 190.0, "change": -0.09, "day_change_percent": -0.0474, "direction": "down", "timestamp": 1791346929.611}, ..., "TSLA": {"ticker": "TSLA", "price": 249.87, "previous_price": 250.0, "prev_close": 250.0, "change": -0.13, "day_change_percent": -0.052, "direction": "down", "timestamp": 1791346929.611}}

```

- Events are unnamed, so the frontend uses `EventSource.onmessage`.
- `data` is a JSON object keyed by ticker with the **full current state of every tracked ticker**. A ticker missing from an event has been removed.
- The first event arrives as soon as the client connects, so a reconnecting client is correct after one message.
- `retry: 1000`, sent once, makes the browser reconnect after one second instead of its default of a few seconds.

```ts
type Direction = "up" | "down" | "flat";

interface PriceUpdate {
  ticker: string;
  price: number;
  previous_price: number;
  prev_close: number;
  change: number;
  day_change_percent: number;
  direction: Direction;
  timestamp: number; // Unix seconds
}

const es = new EventSource("/api/stream/prices");
es.onopen = () => setConnection("connected"); // green dot
es.onerror = () =>
  setConnection(es.readyState === EventSource.CLOSED ? "disconnected" : "reconnecting"); // red / yellow
es.onmessage = (e) => {
  const prices: Record<string, PriceUpdate> = JSON.parse(e.data);
  // For each ticker: flash by comparing with the last price *rendered*,
  // and append { time: timestamp, value: price } to its sparkline buffer.
};
```

Flash on the difference from the last rendered price rather than on `direction`. `direction` compares with the previous cache update, which a slow client may never have rendered.

### 11.5 Tracked Tickers

The tracked set is **the watchlist plus every ticker with an open position**. Without the positions, removing a held ticker from the watchlist would stop its price and break the portfolio value.

```sql
-- tracked_tickers(): what the market data source should be pricing
SELECT ticker FROM watchlist WHERE user_id = 'default'
UNION
SELECT ticker FROM positions WHERE user_id = 'default' AND quantity > 0
```

| Event                                  | Call                                                                                                  |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| App startup                            | `await source.start(tracked_tickers())`                                                               |
| Watchlist add or remove (REST or chat) | Change the DB, then `await source.sync_tickers(tracked_tickers())`                                    |
| Trade                                  | `await source.add_ticker(t)` before reading the fill price; `sync_tickers(...)` after, in a `finally` |

### 11.6 Prices in the Rest of the Backend

These are sketches for the backend agent. `db` stands for the database layer, and `TradeError` for the portfolio service's validation error.

Watchlist routes:

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dependencies import MarketSourceDep, PriceCacheDep
from app.services.market import normalize_ticker

router = APIRouter()


class WatchlistAdd(BaseModel):
    ticker: str


def parse_ticker(raw: str) -> str:
    try:
        return normalize_ticker(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/api/watchlist")
async def get_watchlist(cache: PriceCacheDep) -> list[dict]:
    return [
        quote.to_dict() if (quote := cache.get(t)) else {"ticker": t, "price": None}
        for t in db.watchlist_tickers()
    ]


@router.post("/api/watchlist", status_code=201)
async def add_to_watchlist(body: WatchlistAdd, source: MarketSourceDep, cache: PriceCacheDep) -> dict:
    ticker = parse_ticker(body.ticker)
    db.add_to_watchlist(ticker)  # INSERT OR IGNORE
    await source.sync_tickers(db.tracked_tickers())  # prices the new ticker right away
    quote = cache.get(ticker)
    return quote.to_dict() if quote else {"ticker": ticker, "price": None}


@router.delete("/api/watchlist/{ticker}", status_code=204)
async def remove_from_watchlist(ticker: str, source: MarketSourceDep) -> None:
    db.remove_from_watchlist(parse_ticker(ticker))
    await source.sync_tickers(db.tracked_tickers())  # keeps pricing it while a position is open
```

Trade execution:

```python
async def execute_trade(
    ticker: str, side: str, quantity: float, source: MarketDataSource, cache: PriceCache
) -> dict:
    # `ticker` was already normalized by the caller (route or chat flow)
    await source.add_ticker(ticker)  # no-op if tracked; otherwise start tracking and price it now
    try:
        price = cache.get_price(ticker)
        if price is None:
            raise TradeError(f"No price available for {ticker}")  # HTTP 400, or an error in the chat reply
        ...  # check cash or shares, record the trade and position at `price`, take a portfolio snapshot
    finally:
        await source.sync_tickers(db.tracked_tickers())  # stop tracking it if no position resulted
```

The chat flow reuses both. The LLM's watchlist changes go through the same DB and `sync_tickers` calls, and its trades go through `execute_trade`. A reply like "added PYPL and bought 10 shares" therefore works on every source, because `add_ticker` prices PYPL before the trade reads it.

Portfolio value (positions table, header total, 30s snapshots, LLM context):

```python
price = cache.get_price(position.ticker)
current_price = price if price is not None else position.avg_cost  # no price yet: value at cost
```

LLM context:

```python
def describe(cache: PriceCache, ticker: str) -> str:
    q = cache.get(ticker)
    return f"{ticker} ${q.price:.2f} ({q.day_change_percent:+.2f}% today)" if q else f"{ticker}: no price yet"
```

Health check:

```python
@app.get("/api/health")
async def health(source: MarketSourceDep) -> dict:
    return {"status": "ok", "market_data": source.status()}
```

```json
{"status": "ok", "market_data": {"source": "simulator", "tickers": 10}}
{"status": "ok", "market_data": {"source": "massive", "mode": "eod", "tickers": 10, "last_success": 1791346929.1, "last_error": null}}
```

## 12. Testing

```bash
cd backend
uv run pytest    # 83 tests in about 3s; no network or API key needed
uv run ruff check app tests demos && uv run ruff format --check app tests demos && uv run mypy app demos
```

[MARKET_DATA_SUMMARY.md](MARKET_DATA_SUMMARY.md) §8 lists what each test file covers and how the code was verified beyond the unit tests. The Massive tests pass a `FakeClient` through the `client=` parameter, so they need no network. The statistical tests use fixed seeds, so they are deterministic.

Manual check:

```bash
uv run uvicorn app.main:app --port 8000 --timeout-graceful-shutdown 2
curl -N localhost:8000/api/stream/prices    # an event every 0.5s with the simulator
curl localhost:8000/api/health
uv run python -m demos.market_simulator     # live terminal dashboard of the simulator
```

## 13. Implementation Checklist

Done for the market data code, except steps 5 and 6, which belong to the routes and services still to be built.

1. ✅ Add the dependencies and the pytest settings (§3).
2. ✅ Create `services/market/`.
3. ✅ Add the tests; `uv run pytest` passes.
4. ✅ Add `dependencies.py`, `routes/stream.py`, the lifespan in `main.py`, and `market_data` in `/api/health` (§11).
5. ⬜ Add `tracked_tickers()` to the database layer (§11.5), and call `sync_tickers` / `add_ticker` from the watchlist routes, trade execution and the chat flow (§11.6).
6. ⬜ Apply `normalize_ticker` wherever a ticker enters from outside, in each new route and in the chat flow.
7. ✅ Add `MASSIVE_POLL_SECONDS=` to `.env.example`.
8. ✅ Check by hand with `curl -N` (§12). Repeat with a Massive key when one is available: `/api/health` should show the expected `mode` and no `last_error`.

## 14. Changes from the Earlier Drafts

Unchanged from MARKET_INTERFACE.md and MARKET_SIMULATOR.md: the `PriceUpdate` fields and the SSE payload, the factory rule, the GBM, factor and jump model with its parameters, the ticker profiles, the module layout, and "snapshot first, EOD fallback on the free plan".

**Fixes.** The earlier code misbehaves in these cases:

| #   | Earlier behavior                                                                                                                                                                                                                                                                       | Now                                                                                                          | See   |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ----- |
| F1  | A ticker removed during a Massive poll was written back to the cache and stayed in every SSE event with a frozen price.                                                                                                                                                                | Poll results are written only for tickers still tracked.                                                     | §10.5 |
| F2  | The free-plan EOD walk started at today and went back one calendar day per call. Startup on a Monday or Tuesday morning cost 6 calls (1 probe and 5 grouped), over the 5 calls/min limit. If same-day requests return 403, the walk aborted and the free plan showed no prices at all. | Starts at yesterday (New York), skips weekends without calling, passes over 403 days, stops after 4 lookups. | §10.2 |
| F3  | Finding fewer than two EOD sessions raised `IndexError`, which escaped the poll loop.                                                                                                                                                                                                  | One session gives `prev_close = price`; none is a logged failure.                                            | §10.2 |
| F4  | Any exception other than `BadResponse` or `HTTPError` ended the poll task silently, freezing prices until a restart.                                                                                                                                                                   | A catch-all logs the traceback and the loop carries on with backoff.                                         | §10.4 |
| F5  | The client's default `retries=3` honors `Retry-After` on 429: one rate-limited call blocked a thread for 6s and sent 4 requests (measured at `Retry-After: 2`).                                                                                                                        | `retries=0` with 5s/10s timeouts; the poll loop is the only retry policy.                                    | §10.5 |
| F6  | `is_not_authorized` raised `AttributeError` when the error body was JSON but not an object.                                                                                                                                                                                            | Handles any body, and also matches a "not entitled" message, since the 403 body is unverified.               | §10.3 |

**Design changes:**

| #   | Earlier                                                                                                                  | Now                                                                                                          | Why                                                                                                                                |
| --- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| D1  | `add_ticker` and `remove_ticker` were synchronous; on Massive a new ticker had no price until the next poll (up to 15s). | Coroutines; Massive fetches a new ticker straight away.                                                      | "Add PYPL and buy 10 shares" from chat otherwise fails with 400 on Massive.                                                        |
| D2  | Callers paired adds and removes by hand (four rules).                                                                    | `sync_tickers(watchlist ∪ open positions)`.                                                                  | One idempotent call; any drift is repaired by the next one.                                                                        |
| D3  | The SSE loop sampled the cache every 500ms.                                                                              | It waits on `cache.wait_for_change()`.                                                                       | Ticks no longer arrive up to 500ms late (measured 45, 261 and 453ms against 0.1ms); the cadence follows the source.                |
| D4  | Browser's default reconnect delay.                                                                                       | `retry: 1000` on the first event.                                                                            | Reconnects after 1s.                                                                                                               |
| D5  | Errors retried every 15s.                                                                                                | Exponential backoff up to 5 minutes (at least 60s apart on the free plan), plus `status()` in `/api/health`. | No log spam with a bad key, no burst of retries against the free plan's 5 calls/min, and the reason prices are missing is visible. |
| D6  | Re-adding a ticker to the simulator restarted it at the seed price.                                                      | Removed tickers park their last price; `prev_close` stays the seed price.                                    | No jump back after a remove and re-add.                                                                                            |
| D7  | The cache accepted any float.                                                                                            | It rejects zero, negative, NaN and infinite prices.                                                          | One NaN would make every SSE event invalid JSON.                                                                                   |
| D8  | No ticker validation.                                                                                                    | `normalize_ticker` at the API boundary.                                                                      | Massive is case-sensitive, and the simulator prices anything.                                                                      |
| D9  | Tests replaced `source._client`.                                                                                         | `MassiveDataSource(..., client=...)`.                                                                        | An explicit seam for fakes.                                                                                                        |
| D10 | `profile_for()` ran for every ticker on every tick; a failing tick ended the simulator task.                             | Profiles are cached when a ticker is added; tick errors are logged.                                          | Less work per tick, and the same "never die" rule as Massive.                                                                      |

## 15. Known Limitations

| Limitation                                       | Impact and mitigation                                                                                                                                                                                                            |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The simulator restarts from seed prices          | After a restart, held positions can show a P&L jump. Later fix: start each held ticker from its last trade price (give `GBMSimulator.add()` an optional starting price).                                                         |
| The free Massive plan gives static prices        | EOD closes only, so no flashes and flat sparklines. For a lively demo, leave `MASSIVE_API_KEY` empty.                                                                                                                            |
| Starter and Developer data is 15 minutes delayed | Consider a "delayed" badge in the UI when `/api/health` reports `"source": "massive"`.                                                                                                                                           |
| No market-hours logic                            | The simulator moves 24/7. Massive keeps polling while the market is closed: calls are unlimited on paid plans, and prices just stay flat.                                                                                        |
| EOD mode is sticky                               | After upgrading the plan, restart the app to get snapshots.                                                                                                                                                                      |
| One process                                      | Cache and simulator live in memory, so run a single uvicorn worker.                                                                                                                                                              |
| Not verified against a live free key             | The exact 403 bodies, for the snapshot endpoint and for same-day grouped requests. Detection is deliberately lenient, and the log line "Massive plan has no snapshot access" confirms the switch. Check once a key is available. |

## 16. Changes after the Code Review

From [MARKET_DATA_REVIEW.md](archive/MARKET_DATA_REVIEW.md) (archived). These changes are in the code.

| #   | Problem                                                                                                         | Change                                                                                                                                 |
| --- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | A shutdown with any SSE client attached hung until the client left                                               | Run uvicorn with `--timeout-graceful-shutdown 2` (§11.1, PLAN.md §11); covered by a test                                               |
| M2  | On Massive, each new ticker could hold up a request for the 10s read timeout while the API was down               | `add_ticker`/`sync_tickers` make one batched call, wait at most 3s, and make no call while the API is failing (§10.5)                  |
| L1  | The cache validated before rounding (a sub-cent price became 0.0) and never checked `prev_close` (NaN broke the SSE JSON) | Round first (4 decimals below $1), then validate; an unusable `prev_close` carries the stored one forward (§5)                         |
| L2  | Concurrent refreshes during a plan downgrade could burst past the free plan's 5 calls/min                        | `asyncio.Lock` around `_refresh`; the downgrade switches to EOD once (§10.5)                                                            |
| L3  | The app's INFO logs never appeared under uvicorn                                                                 | `logging.basicConfig(level=INFO)` in `main.py` (§11.1)                                                                                 |
| T   | Behaviors without tests                                                                                          | 19 new tests (76 in all), including the lifespan and `/api/health`; all 11 mutation spot-checks in the review are now caught           |
| N   | No lint, format or type-check config                                                                             | `ruff` (line length 120) and `mypy` in the dev group and configured in `pyproject.toml`; all clean                                      |
