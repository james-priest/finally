# Review of PLAN.md

Reviewed: 2026-10-05

## Summary

The plan is clear, well-motivated, and scoped sensibly for a single-user demo. The biggest risk is that **several agents will build in parallel against contracts that aren't fully defined**: SSE payload, REST response shapes, and how tickers flow between the watchlist, price cache and portfolio. A few behaviors also contradict each other (LLM trade errors, removing a held ticker, "canvas" Recharts). Fixing these before implementation will save rework.

Items are ordered by impact.

---

## 1. Contradictions and Correctness Issues

### 1.1 LLM cannot report trade failures it hasn't seen yet

Section 9 says: "If a trade fails validation, the error is included in the chat response so the LLM can inform the user." But the LLM's message is generated *before* trades execute (step 4 → step 6). The LLM cannot comment on an outcome that doesn't exist yet.

**Options:**

- **A (recommended, simpler):** One LLM call. The backend executes trades and returns each action's result (`ok` / `error` + reason) alongside the message. The frontend renders failures inline. The failure is persisted in `chat_messages.actions`, so the LLM sees it in history on the next turn.
- **B:** Second LLM call after execution to produce a final message. Doubles latency and complexity.

### 1.2 Removing a watched ticker that you hold

If the user removes AAPL from the watchlist while holding AAPL, the price source stops tracking it and the portfolio can no longer be valued. Section 6 says the stream covers "all tickers known to the system — equivalent to the user's watchlist", which is not equivalent once positions exist.

**Recommendation:** The set of tracked tickers is `watchlist ∪ positions`. Alternatively, block removal of held tickers. State one rule explicitly.

### 1.3 Recharts is not canvas-based

Section 10: "Canvas-based charting library preferred (Lightweight Charts or Recharts)". Recharts renders SVG. Lightweight Charts is canvas but has no treemap.

**Recommendation:** Lightweight Charts for the main price chart and P&L chart. For the heatmap, either Recharts `Treemap` or a small hand-rolled squarified layout with divs. Drop the "canvas preferred" wording, since data volume here is tiny.

### 1.4 `users_profile` has no `user_id`

Section 7 says "All tables include a `user_id` column", but `users_profile` uses `id` instead. Minor, but agents follow the text literally. Reword as "all tables except `users_profile` (whose `id` *is* the user id)".

### 1.5 Outdated runtime versions

Node 20 reached end-of-life in April 2026. Use Node 24 (Active LTS) for the build stage. Consider Python 3.13 instead of 3.12 (confirm all dependencies, including LiteLLM, support it).

### 1.6 Browser auto-open

Section 2 says "A browser opens to localhost:8000", but Section 11 says the start script "optionally opens the browser". Pick one (recommend: the script opens it on macOS via `open`, and prints the URL elsewhere).

---

## 2. Missing Contracts (highest-value additions)

Agents can work in parallel only if these shapes are defined up front. I suggest adding a short "API Contracts" section with example JSON for each.

### 2.1 SSE event format

Undefined: one event per ticker, or one batched event per tick? What's the event name, and what's the timestamp format?

Suggested (one batched event per tick, simplest for the client):

```
event: prices
data: {"AAPL": {"price": 191.23, "prev": 191.10, "ts": 1759680000.5}, "MSFT": {...}}
```

- Drop the `direction` field. It's derivable from `price` vs `prev`.
- Clarify whether unchanged prices are sent. With Massive polling every 15s and SSE at 500ms, the same price would be re-sent ~30 times. Recommend: send only tickers whose price changed since the last push, plus a full snapshot on connect.

### 2.2 REST response shapes

Each of these needs an example:

- `GET /api/portfolio`: positions (ticker, quantity, avg_cost, current_price, market_value, unrealized_pnl, pnl_pct), cash, total_value
- `GET /api/watchlist`: ticker, price, prev, daily change %
- `GET /api/portfolio/history`: `[{recorded_at, total_value}]`
- `POST /api/portfolio/trade`: response body on success (updated position + cash?)
- `POST /api/chat`: `{message, actions: [{type: "trade"|"watchlist", ..., status: "ok"|"error", error?}]}`

### 2.3 Error format

Define one error shape and status codes, e.g. `400 {"detail": "Insufficient cash: need $1,912.30, have $500.00"}` (FastAPI's default `HTTPException` shape is fine). Cover these cases: insufficient cash, insufficient shares, unknown ticker, no price available yet, duplicate watchlist add, non-positive quantity.

---

## 3. Questions and Clarifications

### Market data

1. **Daily change %:** Relative to what? The simulator has no "previous close". Suggest: the simulator uses the seed price as the reference, and Massive uses `prevDay.c` from the snapshot endpoint.
2. **Unknown tickers in the simulator:** When the user (or LLM) adds `PYPL`, what price does the simulator start from? Suggest: a known seed table for common tickers, and a random price in $50–$300 otherwise. Should any symbol be accepted (e.g. `ZZZZ`)? With Massive, an invalid ticker returns no data. Should the add be rejected?
3. **Massive endpoint:** Name it. The multi-ticker snapshot endpoint (`/v2/snapshot/locale/us/markets/stocks/tickers?tickers=...`) fetches all tickers in one call, which is what makes 5 calls/min workable.
4. **Interface:** Specify the abstract interface's methods (e.g. `start()`, `stop()`, `add_ticker()`, `remove_ticker()`), so the watchlist service knows how to tell the source about new tickers.

### Portfolio

5. **Average cost:** Confirm the weighted average on buys and no change on sells.
6. **Zero quantity:** Delete the `positions` row when quantity reaches 0? (Recommend yes.) Use a small epsilon or rounding for fractional REAL quantities.
7. **Trading an unwatched ticker:** Can the user buy `PYPL` via the trade bar if it isn't watched? There's no price for it. Suggest: auto-add it to the watchlist, or reject with "no price available".
8. **Realized P&L:** Not tracked anywhere. Fine for scope, but say so explicitly so no agent invents it.
9. **Header total value "updating live":** Is it computed client-side from SSE prices + positions, or by polling `/api/portfolio`? Recommend client-side. It's cheap and stays in sync with the flashing prices.

### Charts

10. **Main chart history:** Like the sparklines, the main chart will be empty on page load and only fills from SSE. Is that acceptable? A small alternative: the backend keeps the last ~N minutes per ticker in memory and exposes `GET /api/prices/{ticker}/history`. If not adding that, state that the main chart also starts empty.
11. **P&L chart on fresh start:** It has one point for the first 30s. Consider recording a snapshot at startup and on page load.

### Chat

12. **History length:** "Recent conversation history": how many messages? Suggest the last 20.
13. **Chat history on reload:** Messages are stored but there's no endpoint to read them, so the chat panel is empty after refresh. Add `GET /api/chat`, or state that this is intended.
14. **Mock mode behavior:** E2E tests need a trade to appear inline, so the mock must produce trades. Define the rules, e.g. "if the message contains `buy <N> <TICKER>`, return that trade; otherwise return a fixed message with no actions".
15. **Structured output schema:** Strict JSON-schema modes typically require all fields to be present. Make `trades` and `watchlist_changes` required arrays (empty when unused) rather than optional. Define the `action` enum as `"add" | "remove"`.

### Infrastructure

16. **DB init timing:** "On startup (or first request)": pick one. Startup, via the FastAPI lifespan, is simpler and avoids race conditions on concurrent first requests.
17. **`.env` location during local dev:** The backend lives in `backend/` but `.env` is at the project root. State how the backend locates it outside Docker (e.g. `load_dotenv` with an explicit path, or the start script only).
18. **`.env.example`:** It's mentioned in the text but missing from the directory tree.
19. **Agent roles and build order:** The plan references a "Frontend Engineer" and "Backend/Market Data agents", but doesn't define their ownership or sequencing. A short table (agent, owns, depends on) would help orchestration.

---

## 4. Opportunities to Simplify

| Area | Current | Suggested |
| --- | --- | --- |
| Positions/watchlist keys | UUID `id` + UNIQUE `(user_id, ticker)` | Composite `PRIMARY KEY (user_id, ticker)`, and drop the UUID |
| `docker-compose.yml` | Optional wrapper alongside the scripts | Drop it. The scripts already cover this, so it's one less thing to maintain |
| SSE `direction` field | Sent per event | Derive client-side from `price` vs `prev` |
| Trade-failure handling | LLM informs user (impossible as written) | Return per-action status; no second LLM call (see 1.1) |
| DB init | Startup *or* first request | Startup only |
| E2E infra | Separate Playwright container via compose | Optionally run Playwright on the host against the running app container. One fewer image to build. Keep the container if CI portability matters |
| E2E "SSE resilience" | Disconnect and verify reconnection | Hard to make deterministic. Consider a unit test of the status indicator's state machine instead |
| E2E "heatmap renders with correct colors" | Pixel/color checks | Assert on a `data-pnl="positive"` attribute rather than colors, which is less brittle |
| Simulator correlation | "Tech stocks move together" | Specify a minimal model: one market factor + one sector factor per ticker. Avoid a full covariance matrix |

---

## 5. Minor Notes

- Money is stored as REAL floats. That's acceptable for a simulation, but round cash and prices to 2 decimals at the API boundary for display consistency.
- Snapshot growth: 2,880 rows/day at 30s intervals is fine for SQLite. No retention policy is needed, but the history endpoint may want a `limit` or time window.
- FastAPI static mount: mount `StaticFiles(directory="static", html=True)` at `/` **after** the API routers, so `/api/*` isn't shadowed.
- The plan says "Massive (Polygon.io)". It's worth one line noting that Polygon rebranded to Massive, so agents searching docs find the right API.
