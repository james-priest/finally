# Market Data Backend: Code Review

Review of the market data subsystem merged in PR #5 (commit `843f184`): `backend/app/services/market/`, `backend/app/routes/stream.py`, `backend/app/dependencies.py`, `backend/app/main.py`, and the tests under `backend/tests/`. Reviewed against PLAN.md §6 and [MARKET_DATA_DESIGN.md](MARKET_DATA_DESIGN.md), with [MASSIVE_API.md](MASSIVE_API.md), [MARKET_INTERFACE.md](MARKET_INTERFACE.md) and [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md) as background.

Date: 2026-10-08 · Python 3.12.14, FastAPI 0.142.2, Starlette 1.7.0, uvicorn 0.54.0, massive 2.8.0, pytest 9.1.1

## 1. Verdict

**Approve, with two medium fixes before the app ships.** The subsystem is well built: small, clearly layered, defensive where it matters, and closely matched to the design. All 57 tests pass, fast and reliably. Every fix the design claims (F1–F6) holds up when checked independently. No finding blocks other agents from building the database, portfolio, chat or frontend on top of it.

| Area                   | Result                                                                                                       |
| ---------------------- | ------------------------------------------------------------------------------------------------------------ |
| Tests                  | **57 / 57 pass** in ~2s. 15 / 15 repeat runs passed, 5 of them under heavy CPU load (16 busy loops on 8 cores) |
| Coverage               | 93% of `app/`. Market package 95–100%; `main.py` 0%                                                          |
| Matches the design      | All 15 code files are **byte-identical** to the code blocks in MARKET_DATA_DESIGN.md                         |
| PLAN.md §6 requirements | All met (R1–R9 in the design's §1)                                                                           |
| Findings               | 2 medium, 4 low, 6 test gaps, 4 tooling and docs nits                                                         |

## 2. How the Review Was Done

1. Read every planning document, then every source and test file.
2. Pulled the code blocks out of MARKET_DATA_DESIGN.md and diffed them against the repo. No differences.
3. Ran the suite: once with durations, 10 times in a row, and 5 times under CPU load. Ran coverage, `ruff` and `mypy`.
4. **Ran the real app** under uvicorn: `/api/health`, `curl -N` on the stream, and a shutdown with a client attached.
5. **Ran the Massive source through the real `massive.RESTClient` over HTTP** against a local fake server acting as the Starter plan, the free plan, a bad key, a 429 rate limit and a 500 error.
6. **SSE checks in-process:** five clients at once, cache waiters released when clients disconnect, and the wire format for edge-case values.
7. **Mutation spot-checks:** applied 11 deliberate bugs, one at a time, to a scratch copy and recorded whether the suite caught each one (§4.3).
8. Wrote targeted scripts for concurrency (a plan downgrade with adds in flight) and latency (`add_ticker` while Massive hangs).

The scripts were throwaway and are not committed. §8 lists the commands for repeating the main checks.

## 3. What Is Good

- **Clean boundaries.** A single cache writer. Only the factory knows which source is running. The ABC's `sync_tickers` makes every caller idempotent. The pure-math `GBMSimulator` sits apart from its asyncio wrapper.
- **The push-on-change SSE design is correct.** `wait_for_change()` swaps in a fresh `asyncio.Event` after each `set()`, so no wake-up is lost. A slow client gets the merged latest state instead of a backlog. Measured: with 5 clients connected there were 5 waiters, every client received every event, and 0 waiters remained after they disconnected.
- **Massive error handling holds up on the real HTTP client:**

  | Scenario                                 | Calls | Time           | Result                                                         |
  | ---------------------------------------- | ----- | -------------- | -------------------------------------------------------------- |
  | Starter plan                             | 1     | 4 ms           | snapshot mode, prices and `prev_close` correct                 |
  | Free plan (403 on snapshot)              | 3     | 5 ms           | switched to EOD, `(192.0, 190.0)` from Friday and Thursday     |
  | Bad key (401)                            | 1     | 2 ms           | stays in snapshot mode, `last_error` set, next try in 30s      |
  | 429 with `Retry-After: 2`                | 1     | 2 ms           | `MaxRetryError`, handled                                        |
  | 500                                      | 1     | 2 ms           | `MaxRetryError`, handled                                        |
  | 429 with the client's default `retries=3` | 4     | **6.0 s**      | confirms why the code sets `retries=0` (fix F5)                 |

- **The simulator's statistics are right.** The tests check per-tick volatility, within- and cross-sector correlation and the jump rate against the model with fixed seeds, so they are deterministic and not flaky.
- **Small but thoughtful details:** `crc32` for stable seed prices, parked prices on re-add, `timestamp is None` rather than `or` (so 0 is valid), `not value >= 1` to reject NaN, and the API key passed explicitly to the client.
- **The tests are good.** `FakeClient` goes in through a proper constructor seam. The in-flight removal race is tested with real thread gates. The SSE test uses a real uvicorn and httpx.

## 4. Test Results

### 4.1 Suite

```
57 passed in 2.07s     (slowest: jump-rate stats 0.34s, SSE end-to-end 0.25s, correlations 0.19s)
```

Repeat runs: 10 / 10 passed. Under load: 5 / 5 passed, at 1.9–2.1s. The timing-based tests (`asyncio.sleep` with 0.01s ticks) have enough margin.

### 4.2 Coverage

| File                         | Cover | Missed                                                                     |
| ---------------------------- | ----- | -------------------------------------------------------------------------- |
| `services/market/cache.py`, `models.py`, `factory.py`, `tickers.py`, `routes/stream.py` | 100% | |
| `services/market/massive.py` | 98%   | `us_market_today()` (54), empty-ticker return (162), non-403 error during the EOD walk (202) |
| `services/market/simulator.py` | 97% | `status()` (156), the tick-error handler (164–165)                          |
| `services/market/base.py`    | 95%   | default `status()` (36)                                                     |
| `dependencies.py`            | 89%   | `get_market_source` (13)                                                    |
| `main.py`                    | **0%** | lifespan and `/api/health`                                                  |

### 4.3 Mutation Spot-Checks

| Mutation                                                    | Caught?      |
| ----------------------------------------------------------- | ------------ |
| F1: drop the "still tracked?" check on poll results          | ✅ caught     |
| F2: EOD walk starts at today                                 | ✅ caught     |
| D5: drop the free plan's 60s retry floor                     | ✅ caught     |
| Cache never replaces its `Event`, so SSE busy-loops          | ✅ caught     |
| Cache accepts NaN                                            | ✅ caught     |
| SSE sends `retry:` on every event                            | ✅ caught     |
| Simulator stops pinning `prev_close` to the seed price (D6)  | ❌ survived → T2 |
| Simulator tick errors are not caught (D10)                   | ❌ survived → T3 |
| `us_market_today()` returns the UTC date                     | ❌ survived → T4 |
| A second `start()` creates a second poll task               | ❌ survived → T5 |
| Simulator `add_ticker` re-writes the price when already tracked | ❌ survived → T5 |

The fixes the design names as mutation-checked are covered. The survivors are behaviours the design promises that have no test (§6).

## 5. Findings

Severity: **Medium** means real impact in normal use and should be fixed before release. **Low** means an edge case or something cosmetic. Line numbers refer to the current files.

### M1 (Medium): Server shutdown hangs while any browser has the stream open

`routes/stream.py:13-21`. The SSE generator loops forever and stops only when the client disconnects. On SIGTERM or SIGINT, uvicorn waits for open connections to close before it runs lifespan shutdown, and it has no timeout by default.

**Reproduced:** started uvicorn, attached `curl -N /api/stream/prices`, sent SIGTERM. The server was **still running 12s later** and logged `Waiting for connections to close`. It exited only after the client was killed.

**Impact:**
- `docker stop` / `scripts/stop_mac.sh` with a browser tab open always waits Docker's 10s grace period and then SIGKILLs. `source.stop()` and any future DB cleanup in the lifespan never run.
- `uvicorn --reload` during development stalls on every reload while the frontend is open.

**Fix (verified):** add `--timeout-graceful-shutdown 2` to the uvicorn command in the Dockerfile `CMD` and in any dev or start script. With it, the server exited 2.1s after SIGTERM with the client still attached, and the lifespan shutdown still ran (`Cancel 1 running task(s), timeout graceful shutdown exceeded` → `Application shutdown complete`). Add a note to MARKET_DATA_DESIGN.md §11.1 next to "single uvicorn worker".

### M2 (Medium): On Massive, `add_ticker` blocks the calling request for up to 10s per ticker when the API is down

`massive.py:100-107`. In snapshot mode, `add_ticker` awaits a snapshot call for the new ticker. `sync_tickers` (`base.py:38-45`) adds tickers one at a time. While Massive is unreachable or hanging, each add waits out the 10s read timeout.

**Reproduced:** a fake server that accepts connections and never answers. `sync_tickers(["PYPL", "AMD"])` took **20.0s**. `POST /api/watchlist`, a trade on a new ticker, or a chat reply that adds tickers would hang the same way. Each failed add also counts toward the background loop's backoff, and the add path logs a misleading "next try in Ns".

**Fix (suggested):**
- Skip the immediate fetch when the source is already failing, and let the background loop price the ticker:
  ```python
  elif not self._failures:  # API known to be failing: the background poll will price it
      await self._refresh([ticker])
  ```
- Also override `sync_tickers` in `MassiveDataSource` so that all new tickers go out in **one** snapshot call. That is cheaper on every plan, and a chat reply that adds five tickers then costs one call instead of five.
- Optionally, bound the wait with `asyncio.wait_for(..., 3)`. The thread finishes in the background, which is harmless.

### L1 (Low): The cache validates `price` before rounding and never validates `prev_close`

`cache.py:29-39`.

- `update("X", 0.004)` passes the `> 0` check and is then stored as **`0.0`**. This is not reachable with the simulator. With Massive it needs a sub-cent price. Sub-dollar prices are also cut to cents (for example $0.4567 → $0.46), so `direction` and flashes can go wrong for penny stocks.
- `prev_close` is rounded but not checked. **Reproduced:** `update("Y", 10.0, prev_close=float("nan"))` put `"prev_close": NaN, "day_change_percent": NaN` on the SSE wire, which the browser's `JSON.parse` rejects for **every** client. This is the same failure D7 was meant to prevent, coming in through another field. Massive's client parses JSON with `json.loads`, which accepts a `NaN` literal, so a malformed upstream payload could trigger it.

**Fix:** round first, then require `price > 0`. Treat a non-finite or non-positive `prev_close` as `None` (carry forward). Optionally keep 4 decimals below $1.

### L2 (Low): Concurrent refreshes during a plan downgrade can exceed the free plan's 5 calls/min

`massive.py:138-158`. A background poll and `add_ticker` calls can run `_refresh` at the same time. When a downgrade 403 arrives, the first one switches to EOD mode and walks the grouped endpoint. The others see `_eod_mode` already set and record a spurious "Massive API error: NOT_AUTHORIZED" failure. **Measured:** a downgrade plus two concurrent adds made 7 calls within 0.2s when no grouped data was found (5 in the normal two-session case). It recovers on the next retry, but `/api/health` briefly shows a misleading error.

**Fix:** serialize `_refresh` with an `asyncio.Lock` in `MassiveDataSource`. That also stops an add and a background poll from making overlapping calls.

### L3 (Low): The app's log lines below WARNING are never shown

No logging is configured, and uvicorn only configures its own loggers. Messages from `app.services.market.*` reach Python's last-resort handler, which shows WARNING and above with no timestamp or level, and drops INFO. **Observed:** "Market data: built-in simulator" / "Massive API, polling every 15s" and "Massive polling recovered…" never appear in the uvicorn output. **Fix:** call `logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")` in `main.py`, or pass `--log-config`.

### L4 (Low, expected): `main.py` is still a placeholder

`tracked_tickers()` returns the hardcoded default list, and the lifespan has no `init_db()`. This matches the design (§11.1, §13 step 5) while the database layer does not exist yet. **The next backend agent must** replace it with the `watchlist ∪ open positions` query and call `sync_tickers` and `add_ticker` from the watchlist routes, trade execution and the chat flow (design §11.5–11.6). The SSE stream and `/api/health` already work today.

## 6. Test Gaps

| #   | Gap                                                                                                         | Suggested test                                                                                       |
| --- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| T1  | `main.py` lifespan and `/api/health` are untested (0%)                                                       | `with TestClient(app) as c:` assert `/api/health` returns `{"status": "ok", "market_data": {"source": "simulator", "tickers": 10}}` with `MASSIVE_API_KEY` unset |
| T2  | `prev_close` staying at the seed price after remove and re-add (D6) is untested at the source level          | `SimulatorDataSource`: tick, remove, re-add; assert `cache.get(t).prev_close == seed` and `price == parked price` |
| T3  | The simulator surviving a failing tick (D10) is untested                                                     | A simulator stub whose `step()` raises once; assert the cache keeps updating                          |
| T4  | `us_market_today()` is untested                                                                              | Freeze `datetime.now` at `2026-10-06T03:00Z` (Monday 23:00 EDT); assert it returns Monday, never Tuesday |
| T5  | Idempotency is untested: `start()` twice (one task) and `add_ticker` on a tracked ticker (no extra cache write) | Count tasks named `market-simulator` / `massive-poller`; assert `cache.version` is unchanged after a repeat add |
| T6  | Shutdown with an open stream (M1), the M2 latency, the L1 edge values                                        | Add with the fixes; L1: `update(t, 0.004)` raises and NaN `prev_close` carries forward                 |

## 7. Tooling and Documentation Nits

- **N1. No formatter or linter config.** The code is written for ~110 columns (max 117). `ruff format --check` at the default 88 columns would reformat 9 files. Add `[tool.ruff] line-length = 120` to `pyproject.toml`. `ruff check` finds only two nits, both in tests: an unsorted import block in `test_massive.py` and nested `with` statements in `test_stream.py:29`.
- **N2. `mypy app` is clean** apart from `massive` shipping no `py.typed`. If mypy is adopted, add `[[tool.mypy.overrides]] module = ["massive.*"] ignore_missing_imports = true`.
- **N3. MASSIVE_API.md is out of date in two places.** Line 5 still points to the superseded MARKET_INTERFACE.md. Its §5.1 `last_two_sessions()` and §6 `RESTClient(... retries=3)` examples contain the patterns that fixes F2, F3 and F5 replaced. Point line 5 at MARKET_DATA_DESIGN.md §10, and mark those snippets "reference only — see design §10".
- **N4. The code and the design document are now two copies of the same code.** The implementation is byte-identical to the design's code blocks, so any fix from this review must go into both, or the two will drift. Recommendation: from now on, treat the code as the source of truth, and add a line to MARKET_DATA_DESIGN.md saying so.

## 8. Recommended Actions

In priority order:

1. **M1:** add `--timeout-graceful-shutdown 2` to the uvicorn command (Dockerfile `CMD` and scripts).
2. **M2:** skip the immediate fetch while the source is failing, and batch adds in `MassiveDataSource.sync_tickers`.
3. **L1:** in the cache, round before validating, and sanitize `prev_close`.
4. **L3:** configure logging in `main.py`.
5. **L2:** add an `asyncio.Lock` around `MassiveDataSource._refresh`.
6. **T1–T6:** add the missing tests (T1 and T2 are about ten lines each).
7. **N1–N4:** tooling config and doc touch-ups.
8. **L4:** handled by the database and portfolio work, as the design plans.

## Appendix: Reproducing

```bash
cd backend
uv sync && uv run pytest -v                                    # 57 passed
uv run --with pytest-cov pytest --cov=app --cov-report=term-missing
uvx ruff check app tests && uv run --with mypy mypy app

# M1: start the server, attach a client, then Ctrl+C the server: it hangs until curl is stopped
uv run uvicorn app.main:app --port 8000
curl -N localhost:8000/api/stream/prices
```

**Environment note (Sprite VM):** the `/.sprite` pyenv `python3` shims hang when invoked, and no Python 3.12 is installed system-wide. `uv sync` therefore hangs at "Searching for Python 3.12". Workaround: `export UV_PYTHON_PREFERENCE=only-managed` before running `uv`. uv then downloads and uses its own 3.12. This does not affect Docker or other machines.

## Resolution (2026-10-08)

Every recommended action in §8 has been carried out on the branch `market-data-review-fixes`, except L4. L4 is the placeholder for the database layer, which the next backend work will replace, as planned.

| Item  | What was done                                                                                                                                                                                           | Verified by                                                                                       |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| M1    | The uvicorn command in PLAN.md §11 and design §11.1 now includes `--timeout-graceful-shutdown 2`, and `main.py` carries a comment saying why                                                                | New test `test_graceful_shutdown_timeout_closes_open_streams` (hangs without the setting). Live: SIGTERM with a client attached exited in 2.2s, lifespan shutdown ran |
| M2    | `MassiveDataSource.sync_tickers` prices all new tickers in one call. `add_ticker` waits at most `ADD_WAIT_SECONDS` (3s); a slower call finishes in the background. No call is made while the API is failing | 3 new tests. Live against a hanging server: `sync_tickers` of 2 tickers went from **20.0s to 3.0s** |
| L1    | The cache rounds first (cents, or 4 decimals below $1), then validates; an unusable `prev_close` carries forward                                                                                           | 5 new tests. Live: the NaN `prev_close` case now sends valid JSON                                    |
| L2    | `asyncio.Lock` around `_refresh`; a targeted refresh that finds EOD mode already on writes stored closes without a call                                                                                    | New test (exact call sequence). Live: downgrade plus 2 concurrent adds went from **7 calls to 5**    |
| L3    | `logging.basicConfig(level=INFO)` in `main.py`                                                                                                                                                             | Live: `INFO app.services.market.factory: Market data: built-in simulator` now appears               |
| T1–T6 | 19 new tests, including a new `tests/test_main.py` (lifespan and `/api/health`)                                                                                                                            | 76 / 76 pass. The new fix tests fail on the old code. All 11 mutation spot-checks are now caught (4 were missed before) |
| N1–N2 | `ruff` and `mypy` added to the dev dependencies and configured in `pyproject.toml` (line length 120; lint rules E, F, W, I, B, UP, SIM, ASYNC, RUF; `massive.*` without stubs). Code formatted and lint fixed | `ruff check`, `ruff format --check` and `mypy app` are all clean                                   |
| N3    | MASSIVE_API.md points to the design doc and marks the snippets that fixes F2, F3 and F5 replaced                                                                                                            | —                                                                                                 |
| N4    | MARKET_DATA_DESIGN.md states that the code is the source of truth and gains §16 summarizing these changes. Its prose for §5, §7, §10.5, §11.1 and §12 is updated                                           | —                                                                                                 |
