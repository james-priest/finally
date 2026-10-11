# Team Contract

The shared agreement for the agent team building the rest of FinAlly. PLAN.md is the spec; this file pins down the details that cross ownership lines. If you need to change something here, message the affected teammates first, then update this file.

## 1. Team and File Ownership

| Agent                  | Owns                                                                                                   |
| ---------------------- | ------------------------------------------------------------------------------------------------------ |
| `database-engineer`    | `backend/db/` (schema SQL, seed, init, data-access functions), `backend/tests/db/`, the `tracked_tickers()` replacement and `init_db()` call in `backend/app/main.py` lifespan |
| `backend-api-engineer` | `backend/app/routes/` (except `chat.py`), `backend/app/services/portfolio.py`, `backend/app/services/watchlist.py`, the snapshot background task, static file serving, all other `backend/app/main.py` wiring, matching tests |
| `llm-engineer`         | `backend/app/services/llm/`, `backend/app/routes/chat.py`, matching tests                              |
| `frontend-engineer`    | `frontend/`                                                                                            |
| `devops-engineer`      | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `scripts/`, root `db/.gitkeep`, root `.gitignore`, root `README.md` |
| `integration-tester`   | `test/` (Playwright E2E + `docker-compose.test.yml`), `planning/E2E_ISSUES.md`                         |

Edit only files you own. If you need a change in someone else's file, message the owner. `backend/pyproject.toml` / `uv.lock`: add dependencies with `uv add` (one agent at a time; retry if the lock is busy).

## 2. Runtime Layout

| Item               | Local                        | Docker                   |
| ------------------ | ---------------------------- | ------------------------ |
| Backend dir (cwd)  | `backend/`                   | `/app/backend`           |
| SQLite file        | `db/finally.db` (repo root)  | `/app/db/finally.db` (volume) |
| Static frontend    | `backend/static/` if present | `/app/backend/static`    |

- DB path: env `DB_PATH`, default `<backend dir>/../db/finally.db`. Tests use a temp path.
- Static dir: env `STATIC_DIR`, default `<backend dir>/static`. Mounted at `/` (with `html=True`) **after** all `/api` routes, only if the directory exists.
- `backend/static/` is a build artifact: gitignored.
- The frontend is a Next.js static export (`frontend/out/`), copied to the static dir by the Dockerfile.

## 3. REST API

All JSON. Errors use FastAPI's shape: `{"detail": "human-readable message"}`. Tickers are normalized with `normalize_ticker` (invalid → **422**). Money values are floats in dollars.

### Portfolio

`GET /api/portfolio` → 200

```json
{
  "cash_balance": 8100.0,
  "positions_value": 1905.0,
  "total_value": 10005.0,
  "unrealized_pnl": 5.0,
  "positions": [
    {
      "ticker": "AAPL",
      "quantity": 10.0,
      "avg_cost": 190.0,
      "current_price": 190.5,
      "market_value": 1905.0,
      "unrealized_pnl": 5.0,
      "unrealized_pnl_percent": 0.2632
    }
  ]
}
```

`current_price` falls back to `avg_cost` when no live price exists. `unrealized_pnl_percent` is a percentage (0.2632 means 0.2632%), rounded to 4 decimals. Positions sorted by ticker.

`POST /api/portfolio/trade` body `{"ticker": "AAPL", "quantity": 10, "side": "buy"}` → 200

```json
{
  "trade": { "id": "uuid", "ticker": "AAPL", "side": "buy", "quantity": 10.0, "price": 190.0, "executed_at": "2026-10-11T12:00:00+00:00" },
  "portfolio": { "...": "same shape as GET /api/portfolio" }
}
```

- `quantity` > 0 (fractional allowed), `side` is `"buy"` or `"sell"`: otherwise **422**.
- Insufficient cash, insufficient shares, or no price available: **400** with a clear `detail`.
- Selling the full quantity deletes the position row. A portfolio snapshot is recorded after every trade.

`GET /api/portfolio/history` → 200 `{"snapshots": [{"total_value": 10000.0, "recorded_at": "ISO"}]}`, oldest first. A snapshot is recorded every 30s by a background task, and once at startup.

### Watchlist

`GET /api/watchlist` → 200 `{"tickers": [{"ticker": "AAPL", "added_at": "ISO", "quote": PriceUpdate | null}]}` in insertion order. `PriceUpdate` is the SSE shape in MARKET_DATA_SUMMARY.md §5.

`POST /api/watchlist` body `{"ticker": "PYPL"}` → **201** with one entry (same shape as above). Already present → **409**.

`DELETE /api/watchlist/{ticker}` → **204**. Not present → **404**.

After any watchlist change or trade, call `source.sync_tickers(tracked_tickers)` (watchlist ∪ open positions) so the SSE stream adds/drops tickers.

### Chat

`POST /api/chat` body `{"message": "buy 5 AAPL"}` → 200

```json
{
  "id": "uuid",
  "role": "assistant",
  "content": "Bought 5 AAPL at $190.00.",
  "actions": {
    "trades": [{ "ticker": "AAPL", "side": "buy", "quantity": 5, "status": "executed", "price": 190.0, "error": null }],
    "watchlist_changes": [{ "ticker": "PYPL", "action": "add", "status": "failed", "error": "PYPL is already on the watchlist" }]
  },
  "created_at": "ISO"
}
```

- `status` is `"executed"` or `"failed"`; `error` is set when failed. Empty arrays when there were no actions.
- LLM failures (network, bad JSON) → 200 with an apologetic `content` and empty actions; never a 500.

`GET /api/chat` → 200 `{"messages": [ ...same shape; user messages have "role": "user" and "actions": null ]}`, oldest first, so the chat panel survives a page reload.

### System

`GET /api/health` → unchanged (MARKET_DATA_SUMMARY.md).

## 4. Shared Backend Services

The LLM chat flow must use the same code paths as the REST routes:

- `app.services.portfolio`: `execute_trade(...)` raises `TradeError(message)` on validation failure and returns the trade dict on success; `get_portfolio(...)` returns the portfolio dict above.
- `app.services.watchlist`: `add_ticker(...)` / `remove_ticker(...)` raise `WatchlistError(message)` on duplicate/missing.

Exact signatures (call the DB-backed ones directly from async code; they are small SQLite queries):

```python
# app.services.portfolio
class TradeError(Exception): ...
async def execute_trade(ticker: str, side: Literal["buy", "sell"], quantity: float,
                        source: MarketDataSource, cache: PriceCache) -> dict  # trade dict, as in POST /api/portfolio/trade
def get_portfolio(cache: PriceCache) -> dict                                  # GET /api/portfolio shape
def get_history() -> list[dict]                                               # [{total_value, recorded_at}], oldest first

# app.services.watchlist
class WatchlistError(Exception): ...
def list_watchlist(cache: PriceCache) -> list[dict]                           # [{ticker, added_at, quote}]
async def add_ticker(ticker: str, source: MarketDataSource, cache: PriceCache) -> dict  # one entry; duplicate -> WatchlistError
async def remove_ticker(ticker: str, source: MarketDataSource) -> None                  # missing -> WatchlistError
```

The services normalize the ticker themselves (invalid → `TradeError` / `WatchlistError`), so the chat flow can pass the LLM's raw symbol. Each one calls `sync_tickers` and takes the post-trade snapshot, so callers do nothing else. Use `str(error)` as the user-facing message.

### Database API (`import db`, package `backend/db/`)

Sync stdlib `sqlite3`, a fresh connection per call (safe in `asyncio.to_thread`). Tickers are stored as given, so normalize them first. Timestamps are ISO UTC strings. Rows come back as plain dicts.

```python
init_db() -> None                          # create tables; seed user ($10k) + 10 tickers if the user row is missing. Idempotent
get_cash() -> float ; set_cash(cash) -> None
get_positions() -> list[dict]              # [{ticker, quantity, avg_cost, updated_at}], sorted by ticker
get_position(ticker) -> dict | None
upsert_position(ticker, quantity, avg_cost) -> None ; delete_position(ticker) -> None
insert_trade(ticker, side, quantity, price) -> dict   # log only
record_trade(ticker, side, quantity, price, cash, position) -> dict
    # ONE transaction: logs the trade, sets cash to `cash`, sets position to (quantity, avg_cost) or deletes it if None.
    # Returns {id, ticker, side, quantity, price, executed_at}
list_watchlist() -> list[dict]             # [{ticker, added_at}], insertion order
watchlist_tickers() -> list[str] ; in_watchlist(ticker) -> bool
add_to_watchlist(ticker) -> dict | None    # {ticker, added_at}; None if already present
remove_from_watchlist(ticker) -> bool      # False if not present
tracked_tickers() -> list[str]             # watchlist ∪ positions with quantity > 0, sorted
insert_snapshot(total_value) -> dict ; list_snapshots() -> list[dict]   # {total_value, recorded_at}, oldest first
insert_chat_message(role, content, actions=None) -> dict              # {id, role, content, actions, created_at}
list_chat_messages(limit=None) -> list[dict]                          # most recent `limit`, oldest first; actions decoded from JSON
```

Tests: `backend/tests/conftest.py` has an autouse fixture `temp_db` that sets `DB_PATH` to a fresh temp file per test. Call `db.init_db()` (or run the lifespan) before using the DB.

## 5. LLM Mock Mode (`LLM_MOCK=true`)

Deterministic, no network. Rules applied to the user message (case-insensitive), first match wins:

| Pattern                         | Actions                         | Content                                  |
| ------------------------------- | ------------------------------- | ---------------------------------------- |
| `buy <qty> <TICKER>`            | one buy trade                   | `Mock: buying <qty> <TICKER>.`           |
| `sell <qty> <TICKER>`           | one sell trade                  | `Mock: selling <qty> <TICKER>.`          |
| `add <TICKER>` / `watch <TICKER>` | one watchlist add             | `Mock: adding <TICKER> to the watchlist.` |
| `remove <TICKER>`               | one watchlist remove            | `Mock: removing <TICKER> from the watchlist.` |
| anything else                   | none                            | `Mock: I received your message.`         |

The mock replaces only the LLM call. Execution, persistence and the response shape are identical to real mode.

## 6. Frontend Test IDs

E2E tests select elements with these `data-testid` values. `{T}` is the ticker symbol.

| Area       | Test IDs                                                                                              |
| ---------- | ----------------------------------------------------------------------------------------------------- |
| Header     | `header-total-value`, `header-cash`, `connection-status` (with `data-status="connected" | "reconnecting" | "disconnected"`) |
| Watchlist  | `watchlist`, `watchlist-row-{T}`, `watchlist-price-{T}`, `watchlist-add-input`, `watchlist-add-button`, `watchlist-remove-{T}` |
| Chart      | `main-chart` (with `data-ticker="{T}"` for the selected ticker)                                        |
| Trade bar  | `trade-ticker-input`, `trade-quantity-input`, `trade-buy-button`, `trade-sell-button`, `trade-error`  |
| Portfolio  | `positions-table`, `position-row-{T}`, `heatmap`, `heatmap-cell-{T}`, `pnl-chart`                      |
| Chat       | `chat-panel`, `chat-input`, `chat-send`, `chat-message` (with `data-role="user" | "assistant"`), `chat-loading`, `chat-action` |

Price and money text is plain numbers formatted like `$10,000.00`, so tests can parse them.
