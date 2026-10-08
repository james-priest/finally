# Massive API Reference (formerly Polygon.io)

Reference for the parts of the Massive REST API that FinAlly uses: current prices for many tickers at once, and end-of-day (EOD) prices. Researched October 2026 against the official docs (`massive.com/docs`) and the official Python client `massive` v2.8.0.

How FinAlly wraps this API is described in [MARKET_DATA_DESIGN.md](MARKET_DATA_DESIGN.md) §10, and the code in `backend/app/services/market/massive.py` is the source of truth. The code samples below are API reference only: FinAlly deliberately does some things differently, as noted.

## 1. Overview

- Polygon.io became **Massive** on Oct 30, 2025. Existing keys and accounts still work.
- REST base URL: `https://api.massive.com` (`https://api.polygon.io` still works for now).
- Official Python client: `massive` on PyPI (`uv add massive`), Python 3.9+.
- Every documentation page is also available as Markdown: add `.md` to the URL. The full index is at `https://massive.com/docs/llms.txt`.
- Tickers are **case-sensitive**. Always send them in upper case (`AAPL`, not `aapl`).

## 2. Authentication

Use either form:

```bash
# Query string
curl "https://api.massive.com/v2/aggs/ticker/AAPL/prev?apiKey=$MASSIVE_API_KEY"

# Header (what the Python client sends)
curl -H "Authorization: Bearer $MASSIVE_API_KEY" "https://api.massive.com/v2/aggs/ticker/AAPL/prev"
```

Responses captured from the live API:

| Case        | HTTP | Body                                                                 |
| ----------- | ---- | -------------------------------------------------------------------- |
| No key      | 401  | `{"status":"ERROR","request_id":"...","error":"API Key was not provided"}` |
| Invalid key | 401  | `{"status":"ERROR","request_id":"...","error":"Unknown API Key"}`    |

Two other errors were not verified live, because no key was available while writing this:

| Case                            | HTTP | Expected body (from Polygon's past behavior)                                  |
| ------------------------------- | ---- | ------------------------------------------------------------------------------ |
| Endpoint not in your plan       | 403  | `{"status":"NOT_AUTHORIZED","request_id":"...","message":"You are not entitled to this data. ..."}` |
| Rate limit exceeded (free plan) | 429  | `{"status":"ERROR","request_id":"...","error":"You've exceeded the maximum requests per minute..."}` |

## 3. Plans, Limits, and Data Freshness

From `massive.com/pricing` (Stocks, individual plans):

| Plan                 | Price   | Rate limit       | Freshness          | Snapshot | Last Trade |
| -------------------- | ------- | ---------------- | ------------------ | -------- | ---------- |
| Stocks Basic (free)  | $0      | **5 calls/min**  | **End of day**     | No       | No         |
| Stocks Starter       | $29/mo  | Unlimited        | 15-minute delayed  | Yes      | No         |
| Stocks Developer     | $79/mo  | Unlimited        | 15-minute delayed  | Yes      | Yes        |
| Stocks Advanced      | $199/mo | Unlimited        | Real-time          | Yes      | Yes        |

What each plan can call, from each endpoint's "Plan Access" section:

| Endpoint                         | Path                                                   | Basic (free) | Starter+ |
| -------------------------------- | ------------------------------------------------------ | ------------ | -------- |
| Full Market Snapshot (multi)     | `GET /v2/snapshot/locale/us/markets/stocks/tickers`    | No           | Yes      |
| Single Ticker Snapshot           | `GET /v2/snapshot/locale/us/markets/stocks/tickers/{T}` | No           | Yes      |
| Unified Snapshot (multi)         | `GET /v3/snapshot`                                     | No           | Yes      |
| Last Trade                       | `GET /v2/last/trade/{T}`                               | No           | Developer+ |
| Daily Market Summary (grouped)   | `GET /v2/aggs/grouped/locale/us/market/stocks/{date}`  | Yes (EOD)    | Yes      |
| Previous Day Bar                 | `GET /v2/aggs/ticker/{T}/prev`                         | Yes (EOD)    | Yes      |
| Daily Ticker Summary (open/close)| `GET /v1/open-close/{T}/{date}`                        | Yes (EOD)    | Yes      |
| Custom Bars (aggregates)         | `GET /v2/aggs/ticker/{T}/range/{m}/{span}/{from}/{to}` | Yes (EOD)    | Yes      |
| Market Status                    | `GET /v1/marketstatus/now`                             | Yes          | Yes      |

**What this means for FinAlly:**

- **Starter or higher:** poll the Full Market Snapshot every few seconds. One call returns every watched ticker.
- **Free plan:** snapshots are not available, so intraday prices are not available either. The best option is the Daily Market Summary, which returns end-of-day closes for every US stock in one call. Prices only change once a day, so on the free plan prices will look static.

## 4. Current Prices for Multiple Tickers

### 4.1 Full Market Snapshot (recommended)

`GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,TSLA`

Returns the latest data for the listed tickers in **one request**. Leave out `tickers` to get the whole market (10,000+ tickers).

| Query param   | Type    | Notes                                                     |
| ------------- | ------- | --------------------------------------------------------- |
| `tickers`     | string  | Comma-separated, case-sensitive. Empty means all tickers. |
| `include_otc` | boolean | Default `false`.                                          |

Response (sample from the docs, trimmed):

```json
{
  "status": "OK",
  "count": 1,
  "tickers": [
    {
      "ticker": "BCAT",
      "todaysChange": -0.124,
      "todaysChangePerc": -0.601,
      "updated": 1605192894630916600,
      "day":     { "o": 20.64, "h": 20.64, "l": 20.506, "c": 20.506, "v": 37216, "vw": 20.616 },
      "min":     { "o": 20.506, "h": 20.506, "l": 20.506, "c": 20.506, "v": 5000, "av": 37216, "n": 1, "t": 1684428600000 },
      "prevDay": { "o": 20.79, "h": 21, "l": 20.5, "c": 20.63, "v": 292738, "vw": 20.6939 },
      "lastTrade": { "p": 20.506, "s": 2416, "t": 1605192894630916600, "x": 4, "c": [14, 41], "i": "71675577320245" },
      "lastQuote": { "p": 20.5, "s": 13, "P": 20.6, "S": 22, "t": 1605192959994246100 }
    }
  ]
}
```

| JSON field         | Python client attribute     | Meaning                                                 |
| ------------------ | --------------------------- | ------------------------------------------------------- |
| `lastTrade.p`      | `snap.last_trade.price`     | Last trade price. **Only on plans that include trades** (Developer+). |
| `min.c`            | `snap.min.close`            | Close of the latest minute bar                          |
| `day.c`            | `snap.day.close`            | Today's bar close so far                                |
| `prevDay.c`        | `snap.prev_day.close`       | Previous session close (the base for daily change)      |
| `todaysChangePerc` | `snap.todays_change_percent`| % change vs previous close                              |
| `updated`          | `snap.updated`              | Last update, **nanoseconds** since epoch                |

Notes:
- **On Starter, `lastTrade` is missing.** Use `min.c`, then `day.c`, then `prevDay.c`, in that order.
- Snapshot data is cleared at **3:30 AM ET** and starts filling again from about 4:00 AM ET. Early in the morning `day` and `min` may be zero or missing, so fall back to `prevDay.c`.
- Timestamp units vary by field. `updated` and `lastTrade.t` are in **nanoseconds**. `min.t` and aggregate `t` are in **milliseconds**.

Python client:

```python
from massive import RESTClient

client = RESTClient(api_key=api_key)  # pass the key explicitly (see Section 6)

snapshots = client.get_snapshot_all("stocks", tickers=["AAPL", "MSFT", "TSLA"])
for snap in snapshots:
    price = (
        (snap.last_trade.price if snap.last_trade else None)
        or (snap.min.close if snap.min else None)
        or (snap.day.close if snap.day else None)
        or (snap.prev_day.close if snap.prev_day else None)
    )
    print(snap.ticker, price, snap.todays_change_percent)
```

The client joins a list into `tickers=AAPL,MSFT,TSLA`. This was checked by inspecting the request it builds: `GET https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers` with `{'tickers': 'AAPL,MSFT,TSLA', 'include_otc': 'false'}`.

### 4.2 Unified Snapshot (alternative)

`GET /v3/snapshot?ticker.any_of=AAPL,MSFT&limit=250`

This newer endpoint works across asset classes and uses snake_case JSON (`last_trade.price`, `session.close`, `session.previous_close`, `session.change_percent`). It is paginated: at most 250 tickers per page, and **the default page size is 10**. It is on the same plans as 4.1.

```python
snaps = list(client.list_universal_snapshots(ticker_any_of=["AAPL", "MSFT"], limit=250))
for s in snaps:
    if s.error:            # unknown tickers come back as {"error": "NOT_FOUND", ...}
        continue
    print(s.ticker, s.session.close, s.session.previous_close)
```

Pass `ticker_any_of` as a **list**. The client calls `",".join(value)` on it, so a plain string would come out as `A,A,P,L`.

FinAlly uses 4.1 instead. Its response is flat, it needs no pagination, and the client returns plain `TickerSnapshot` objects.

### 4.3 Single ticker and last trade

```python
snap = client.get_snapshot_ticker("stocks", "AAPL")   # GET /v2/snapshot/locale/us/markets/stocks/tickers/AAPL
trade = client.get_last_trade("AAPL")                  # GET /v2/last/trade/AAPL  (Developer+)
print(snap.day.close, trade.price, trade.sip_timestamp)
```

Both are one call per ticker, so polling them for a watchlist does not scale. Use 4.1.

## 5. End-of-Day Prices

### 5.1 Daily Market Summary (grouped daily) — all tickers in one call

`GET /v2/aggs/grouped/locale/us/market/stocks/{YYYY-MM-DD}?adjusted=true`

Returns OHLCV for **every** US stock for one trading day. Available on the free plan, so it is the only way a free key can price a whole watchlist within 5 calls/min.

```json
{
  "status": "OK",
  "adjusted": true,
  "queryCount": 3,
  "resultsCount": 3,
  "results": [
    { "T": "AAPL", "o": 115.55, "h": 117.59, "l": 114.13, "c": 115.97, "v": 131704427, "vw": 116.3058, "n": 1000, "t": 1605042000000 }
  ]
}
```

> **Reference only — do not copy.** This sketch starts at today, steps back one calendar day per call and assumes two sessions are found. FinAlly's version starts at yesterday (New York), skips weekends without a call, passes over 403 days, stops after 4 lookups and copes with fewer than two sessions (MARKET_DATA_DESIGN.md §10.2, fixes F2 and F3).

```python
from datetime import date, timedelta

def last_two_sessions(client) -> tuple[dict, dict]:
    """Grouped daily bars for the two most recent trading days (skips weekends/holidays)."""
    sessions, day = [], date.today()
    for _ in range(10):
        aggs = client.get_grouped_daily_aggs(day.isoformat())  # [] when the market was closed
        if aggs:
            sessions.append({a.ticker: a for a in aggs})
            if len(sessions) == 2:
                break
        day -= timedelta(days=1)
    return sessions[0], sessions[1]

latest, previous = last_two_sessions(client)
aapl_close = latest["AAPL"].close
aapl_day_change = (aapl_close / previous["AAPL"].close - 1) * 100
```

The client returns `[]` when `results` is missing, e.g. for a weekend, a holiday, or today before the close on the free plan. Each step back costs one call. Over a long weekend that can be 4–5 calls, which is the whole free-plan minute, so run this once at startup and then hourly at most.

### 5.2 Previous Day Bar — one ticker

`GET /v2/aggs/ticker/{ticker}/prev`

```python
prev = client.get_previous_close_agg("AAPL")   # returns a list with one PreviousCloseAgg
print(prev[0].close, prev[0].timestamp)
```

### 5.3 Daily Ticker Summary — one ticker, one date

`GET /v1/open-close/{ticker}/{date}`, which includes `preMarket` and `afterHours` prices.

```python
oc = client.get_daily_open_close_agg("AAPL", "2026-10-05")
print(oc.open, oc.close, oc.pre_market, oc.after_hours)
```

### 5.4 Custom Bars — history for charts

`GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`. Use `timespan` of `minute`, `hour`, `day`, `week`, …; the dates are `YYYY-MM-DD` or ms timestamps.

```python
bars = client.get_aggs("AAPL", 1, "day", "2026-09-01", "2026-10-05")       # single page, list
for bar in client.list_aggs("AAPL", 5, "minute", "2026-10-05", "2026-10-05", limit=50000):  # auto-paginates
    print(bar.timestamp, bar.close)                                          # timestamp in ms
```

FinAlly does not need this yet, because sparklines are built from the SSE stream. It is listed here in case pre-filled charts are wanted later.

## 6. Python Client Notes

The defaults are shown below. FinAlly uses `connect_timeout=5.0`, `read_timeout=10.0` and **`retries=0`**: the client's retries honor `Retry-After` on 429, which blocked a call for 6s and sent 4 requests in a test, and they spend the free plan's 5 calls/min (MARKET_DATA_DESIGN.md §10.5, fix F5).

```python
from massive import RESTClient

client = RESTClient(
    api_key=api_key,     # required in practice (see below)
    connect_timeout=10.0,
    read_timeout=10.0,
    retries=3,           # urllib3 retries on 413/429/499/500/502/503/504, backoff 0.1s, 0.2s, 0.4s
    pagination=True,     # list_* methods follow next_url automatically
    trace=False,         # True + verbose=True logs request URL and headers (key redacted)
)
```

- **Pass `api_key` explicitly.** The default is `os.getenv("MASSIVE_API_KEY")`, but that runs **when the module is imported**. If `.env` is loaded after the import, the client sees no key and raises `AuthError`.
- **The client is synchronous** (it uses urllib3). In FastAPI/asyncio, call it with `await asyncio.to_thread(client.get_snapshot_all, ...)` so it does not block the event loop.
- **Errors** (checked against the client source and a live run):

| Exception                                | When                                          |
| ---------------------------------------- | --------------------------------------------- |
| `massive.exceptions.AuthError`           | Constructor called with `api_key=None`        |
| `massive.exceptions.BadResponse`         | Any non-200 response. `str(e)` is the raw JSON body, so use `json.loads(str(e))["status"]` to tell `NOT_AUTHORIZED` from `ERROR`. |
| `urllib3.exceptions.MaxRetryError` (an `urllib3.exceptions.HTTPError`) | DNS/connection failures, or when retries run out on 429/5xx |

- Results are typed dataclasses (`TickerSnapshot`, `Agg`, `GroupedDailyAgg`, `LastTrade`). Fields the response leaves out are `None`, so check before you dereference (`snap.last_trade.price if snap.last_trade else None`).
- `raw=True` on any method returns the urllib3 response, if you ever need fields the models do not have.

## 7. Market Status

`GET /v1/marketstatus/now`, available on every plan:

```python
status = client.get_market_status()
print(status.market)          # "open", "closed", or "extended-hours"
print(status.early_hours, status.after_hours, status.server_time)
```

This could be used to poll less often when the market is closed. FinAlly keeps a fixed interval for simplicity.

## 8. WebSockets (not used)

Starter and higher plans can stream trades and per-second or per-minute aggregates over WebSocket (`WebSocketClient(api_key=..., subscriptions=["T.AAPL"])`). FinAlly uses REST polling by design (see PLAN.md §6). It works on every plan that has snapshots and needs no connection management.

## Sources

- Massive docs index: https://massive.com/docs/llms.txt
- REST quickstart (auth): https://massive.com/docs/rest/quickstart.md
- Full Market Snapshot: https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot.md
- Unified Snapshot: https://massive.com/docs/rest/stocks/snapshots/unified-snapshot.md
- Daily Market Summary: https://massive.com/docs/rest/stocks/aggregates/daily-market-summary.md
- Previous Day Bar: https://massive.com/docs/rest/stocks/aggregates/previous-day-bar.md
- Last Trade: https://massive.com/docs/rest/stocks/trades-quotes/last-trade.md
- Market Status: https://massive.com/docs/rest/stocks/market-operations/market-status.md
- Pricing: https://massive.com/pricing
- Python client source: https://github.com/massive-com/client-python (`massive/rest/snapshot.py`, `aggs.py`, `base.py`, `models/`)
