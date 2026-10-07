# Market Data Interface

The unified Python API FinAlly uses for stock prices. The backend talks to one interface, `MarketDataSource`, and gets its prices from one shared `PriceCache`. A factory picks the implementation at startup:

- `MASSIVE_API_KEY` set and non-empty → `MassiveDataSource` (real data, REST polling)
- otherwise → `SimulatorDataSource` (GBM simulator, see [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md))

Massive endpoint details are in [MASSIVE_API.md](MASSIVE_API.md). All the code below was prototyped and tested (8 unit tests, plus an in-process SSE check against FastAPI 0.142.2 and massive 2.8.0).

## 1. Architecture

```
                         ┌──────────────────────────────┐
  MASSIVE_API_KEY? ──►   │ create_market_data_source()  │
                         └──────────────┬───────────────┘
                     ┌──────────────────┴──────────────────┐
                     ▼                                     ▼
          SimulatorDataSource                    MassiveDataSource
          (asyncio task, 500ms tick)             (asyncio task, poll 15s;
                     │                            EOD fallback on free plan)
                     └──────────────┬──────────────────────┘
                                    ▼  cache.update(...)
                              ┌────────────┐
                              │ PriceCache │  latest PriceUpdate per ticker
                              └─────┬──────┘
           ┌────────────────────────┼─────────────────────────┐
           ▼                        ▼                         ▼
  GET /api/stream/prices    trade execution             portfolio valuation,
  (SSE, every ~500ms)       (fill at cache price)       snapshots, LLM context
```

Rules:

- **One writer, many readers.** Only the active source writes to the cache. Everything else only reads.
- **Nothing outside `market/` knows which source is running.** Routes and services use `PriceCache` for prices, and call `add_ticker`/`remove_ticker` on the source to change what is tracked.
- **Everything runs on the event loop.** The Massive client is synchronous, so it runs in `asyncio.to_thread`, but the cache is written only after control returns to the loop. Because of that the cache needs no lock.

## 2. Module Layout

Following the backend's layered structure. Market data is service-layer logic, so it lives in its own service package. `app` is a placeholder for the backend app name.

```
backend/
  app/
    main.py                 # FastAPI app + lifespan (starts/stops the source)
    routes/
      stream.py             # GET /api/stream/prices (SSE)
    services/
      market/
        __init__.py         # public API: PriceCache, PriceUpdate, MarketDataSource, create_market_data_source
        models.py           # PriceUpdate
        cache.py            # PriceCache
        base.py             # MarketDataSource (ABC)
        factory.py          # create_market_data_source()
        simulator.py        # GBMSimulator + SimulatorDataSource
        massive.py          # MassiveDataSource
  tests/
    services/market/test_market.py
```

Dependency: `uv add massive` (pulls in urllib3 and certifi).

## 3. Data Model — `models.py`

`PriceUpdate` is the one price record. It is stored in the cache, used by services, and serialized for SSE.

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Latest price for one ticker, as held in the cache and sent over SSE."""

    ticker: str
    price: float
    previous_price: float
    prev_close: float
    timestamp: float

    @property
    def change(self) -> float:
        return self.price - self.previous_price

    @property
    def direction(self) -> str:
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def day_change_percent(self) -> float:
        return (self.price - self.prev_close) / self.prev_close * 100

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "prev_close": self.prev_close,
            "change": round(self.change, 4),
            "day_change_percent": round(self.day_change_percent, 4),
            "direction": self.direction,
            "timestamp": self.timestamp,
        }
```

| Field            | Meaning                                                                                       |
| ---------------- | --------------------------------------------------------------------------------------------- |
| `price`          | Latest price, rounded to 2 decimals                                                           |
| `previous_price` | Price from the previous update (previous tick or poll). Drives the flash and `direction`.     |
| `prev_close`     | Reference price for the daily change. Massive: previous session close. Simulator: seed price. |
| `timestamp`      | Unix seconds when the cache received the update                                               |

## 4. Price Cache — `cache.py`

```python
import time

from .models import PriceUpdate


class PriceCache:
    """Latest price per ticker. Written by the market data source, read by everyone else.

    All reads and writes happen on the event loop thread, so no lock is needed.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self.version = 0

    def update(
        self,
        ticker: str,
        price: float,
        prev_close: float | None = None,
        timestamp: float | None = None,
    ) -> PriceUpdate:
        """Store a new price. The old price becomes previous_price."""
        old = self._prices.get(ticker)
        price = round(price, 2)
        if prev_close is None:
            prev_close = old.prev_close if old else price
        update = PriceUpdate(
            ticker=ticker,
            price=price,
            previous_price=old.price if old else price,
            prev_close=round(prev_close, 2),
            timestamp=timestamp or time.time(),
        )
        self._prices[ticker] = update
        self.version += 1
        return update

    def get(self, ticker: str) -> PriceUpdate | None:
        return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        update = self._prices.get(ticker)
        return update.price if update else None

    def all(self) -> dict[str, PriceUpdate]:
        return dict(self._prices)

    def remove(self, ticker: str) -> None:
        if self._prices.pop(ticker, None):
            self.version += 1
```

`version` goes up on every change. The SSE loop compares it with the last value it sent, so it only pushes when something actually changed.

## 5. The Interface — `base.py`

```python
from abc import ABC, abstractmethod
from collections.abc import Iterable


class MarketDataSource(ABC):
    """Produces prices for a set of tickers and writes them into a PriceCache."""

    @abstractmethod
    async def start(self, tickers: Iterable[str]) -> None:
        """Begin producing prices for the given tickers in a background task."""

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task."""

    @abstractmethod
    def add_ticker(self, ticker: str) -> None:
        """Start tracking a ticker. No-op if already tracked."""

    @abstractmethod
    def remove_ticker(self, ticker: str) -> None:
        """Stop tracking a ticker and drop it from the cache."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Tickers currently tracked."""
```

How each implementation behaves:

| Behavior                       | Simulator                              | Massive (Starter+)                 | Massive (free plan)                   |
| ------------------------------ | -------------------------------------- | ---------------------------------- | ------------------------------------- |
| Update cadence                 | 500ms                                  | `MASSIVE_POLL_SECONDS` (default 15)| hourly (EOD data)                     |
| Price after `start()` returns  | yes, at the seed price                 | yes, from the first poll           | yes, from the first poll              |
| Price after `add_ticker()`     | right away (seeded)                    | on the next poll                   | right away if the ticker is in the EOD data |
| `prev_close`                   | seed price                             | `prevDay.c`                        | previous session close                |
| Unknown or invalid ticker      | gets a generated price                 | no price (left out of the response)| no price                              |

`add_ticker` and `remove_ticker` are synchronous because they only change in-memory state. Callers must handle "no price yet" (`cache.get_price(t) is None`). For example, a trade on a ticker that has no price should return 400.

## 6. Factory — `factory.py`

```python
import os

from .base import MarketDataSource
from .cache import PriceCache
from .massive import MassiveDataSource
from .simulator import SimulatorDataSource


def create_market_data_source(cache: PriceCache) -> MarketDataSource:
    """Massive if MASSIVE_API_KEY is set and non-empty, otherwise the simulator."""
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        poll_seconds = float(os.environ.get("MASSIVE_POLL_SECONDS", "15"))
        return MassiveDataSource(cache, api_key, poll_seconds=poll_seconds)
    return SimulatorDataSource(cache)
```

| Env var                | Default | Effect                                                                    |
| ---------------------- | ------- | ------------------------------------------------------------------------- |
| `MASSIVE_API_KEY`      | empty   | Set → Massive; empty or whitespace → simulator                            |
| `MASSIVE_POLL_SECONDS` | `15`    | Snapshot poll interval. Paid plans have unlimited calls, so 2–5 is fine.  |

`MASSIVE_POLL_SECONDS` is new. Add it to `.env.example` as an optional variable.

## 7. Massive Implementation — `massive.py`

```python
import asyncio
import json
import logging
from collections.abc import Iterable
from contextlib import suppress
from datetime import date, timedelta

from massive import RESTClient
from massive.exceptions import BadResponse
from massive.rest.models import TickerSnapshot
from urllib3.exceptions import HTTPError

from .base import MarketDataSource
from .cache import PriceCache

logger = logging.getLogger(__name__)

EOD_POLL_SECONDS = 3600.0


def snapshot_price(snap: TickerSnapshot) -> float | None:
    """Best available price: last trade, then minute bar, then day bar, then previous close."""
    candidates = (
        snap.last_trade.price if snap.last_trade else None,
        snap.min.close if snap.min else None,
        snap.day.close if snap.day else None,
        snap.prev_day.close if snap.prev_day else None,
    )
    return next((p for p in candidates if p), None)


def is_not_authorized(error: BadResponse) -> bool:
    """True when the plan does not include the endpoint (HTTP 403, status NOT_AUTHORIZED)."""
    with suppress(ValueError):
        return json.loads(str(error)).get("status") == "NOT_AUTHORIZED"
    return False


class MassiveDataSource(MarketDataSource):
    """Polls the Massive REST API and writes prices into the cache.

    Uses the snapshot endpoint (one call for all tickers; Starter plan and up).
    If the key's plan lacks snapshot access (free Basic plan), falls back to
    end-of-day closes from the grouped daily endpoint, refreshed hourly.
    """

    def __init__(self, cache: PriceCache, api_key: str, poll_seconds: float = 15.0) -> None:
        self._cache = cache
        self._client = RESTClient(api_key=api_key)
        self._poll_seconds = poll_seconds
        self._tickers: set[str] = set()
        self._eod_mode = False
        self._eod_closes: dict[str, tuple[float, float]] = {}
        self._task: asyncio.Task | None = None

    async def start(self, tickers: Iterable[str]) -> None:
        self._tickers.update(tickers)
        await self._poll()
        self._task = asyncio.create_task(self._run(), name="massive-poller")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    def add_ticker(self, ticker: str) -> None:
        self._tickers.add(ticker)
        if ticker in self._eod_closes:
            self._write_eod(ticker)

    def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self._tickers)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(EOD_POLL_SECONDS if self._eod_mode else self._poll_seconds)
            await self._poll()

    async def _poll(self) -> None:
        try:
            if self._eod_mode:
                await self._poll_eod()
            else:
                await self._poll_snapshot()
        except BadResponse as e:
            if not self._eod_mode and is_not_authorized(e):
                logger.warning("Massive plan lacks snapshot access; using end-of-day prices")
                self._eod_mode = True
                await self._poll()
            else:
                logger.error("Massive request failed: %s", e)
        except HTTPError as e:
            logger.error("Massive network error: %s", e)

    async def _poll_snapshot(self) -> None:
        if not self._tickers:
            return
        snapshots = await asyncio.to_thread(
            self._client.get_snapshot_all, "stocks", tickers=sorted(self._tickers)
        )
        for snap in snapshots:
            price = snapshot_price(snap)
            if price is None:
                continue
            prev_close = snap.prev_day.close if snap.prev_day and snap.prev_day.close else None
            self._cache.update(snap.ticker, price, prev_close=prev_close)

    async def _poll_eod(self) -> None:
        latest, previous = await asyncio.to_thread(self._last_two_sessions)
        self._eod_closes = {
            t: (agg.close, previous[t].close if t in previous else agg.close)
            for t, agg in latest.items()
        }
        for ticker in self._tickers:
            if ticker in self._eod_closes:
                self._write_eod(ticker)

    def _last_two_sessions(self) -> tuple[dict, dict]:
        """Grouped daily bars for the two most recent trading days (walks back over weekends/holidays)."""
        sessions: list[dict] = []
        day = date.today()
        for _ in range(10):
            aggs = self._client.get_grouped_daily_aggs(day.isoformat())
            if aggs:
                sessions.append({a.ticker: a for a in aggs})
                if len(sessions) == 2:
                    break
            day -= timedelta(days=1)
        return sessions[0], sessions[1]

    def _write_eod(self, ticker: str) -> None:
        close, prev_close = self._eod_closes[ticker]
        self._cache.update(ticker, close, prev_close=prev_close)
```

Design notes:

- **One HTTP call per poll**, whatever the watchlist size (the snapshot endpoint takes a comma-separated list).
- **The poll loop must never die.** Expected failures are API errors (`BadResponse`) and network errors (`urllib3.exceptions.HTTPError`, which includes `MaxRetryError`). They are logged, the cache keeps its last prices, and the next poll tries again. Other exceptions are bugs and should be allowed to surface.
- **Free-plan fallback.** The first 403 `NOT_AUTHORIZED` from the snapshot endpoint switches the source to EOD mode for the rest of the process. In EOD mode prices are static between hourly refreshes, so there are no flashes and the sparklines stay flat. That is the limit of the free plan. The exact 403 body was not checked against a live free key (see MASSIVE_API.md §2). Confirm it once a key is available.
- **Re-polling an unchanged price** (market closed) sets `previous_price == price`, so `direction` is `"flat"`. That is correct.
- **The key is passed explicitly** to `RESTClient`. Its default reads the env var at import time, which is before `.env` is loaded.

## 8. FastAPI Integration

### 8.1 Lifespan — `main.py`

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.services.market import PriceCache, create_market_data_source


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(tracked_tickers())  # watchlist ∪ open positions, from the DB
    app.state.price_cache = cache
    app.state.market_source = source
    yield
    await source.stop()


app = FastAPI(lifespan=lifespan)
```

Services get the cache and the source from `request.app.state`, or from small dependencies:

```python
from fastapi import Request

def get_price_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache

def get_market_source(request: Request) -> MarketDataSource:
    return request.app.state.market_source
```

### 8.2 Which tickers are tracked

The tracked set is **watchlist ∪ tickers with an open position**. Without positions, removing a held ticker from the watchlist would drop its price, and portfolio valuation would break.

| Event                                      | Call                                  |
| ------------------------------------------ | ------------------------------------- |
| Ticker added to watchlist (REST or LLM)    | `source.add_ticker(t)`                |
| Ticker removed from watchlist              | `source.remove_ticker(t)` only if no open position |
| Position fully sold                        | `source.remove_ticker(t)` only if not in watchlist |
| Buy of a ticker not tracked yet            | `source.add_ticker(t)`, then read the price; reject with 400 if it is still `None` |

### 8.3 SSE endpoint — `routes/stream.py`

FastAPI 0.135+ supports SSE natively (`fastapi.sse`). It sets `Cache-Control: no-cache` and `X-Accel-Buffering: no` and sends keep-alive pings automatically. It also stops the generator when the client disconnects.

```python
import asyncio
from collections.abc import AsyncIterable

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.services.market import PriceCache

router = APIRouter()


@router.get("/api/stream/prices", response_class=EventSourceResponse)
async def stream_prices(request: Request) -> AsyncIterable[ServerSentEvent]:
    cache: PriceCache = request.app.state.price_cache
    last_version = -1
    while True:
        if cache.version != last_version:
            last_version = cache.version
            yield ServerSentEvent(data={t: u.to_dict() for t, u in cache.all().items()})
        await asyncio.sleep(0.5)
```

### 8.4 SSE contract (for the frontend)

Each event is an unnamed `message`, so the frontend can use `EventSource.onmessage`. Its `data` is a JSON object keyed by ticker, holding the **full current state of every tracked ticker**. Captured output:

```
data: {"AAPL": {"ticker": "AAPL", "price": 189.95, "previous_price": 190.0, "prev_close": 190.0, "change": -0.05, "day_change_percent": -0.0263, "direction": "down", "timestamp": 1791299007.58}, "GOOGL": {...}, ...}
```

```ts
const es = new EventSource("/api/stream/prices");
es.onmessage = (e) => {
  const prices: Record<string, PriceUpdate> = JSON.parse(e.data);
  // For each ticker: compare with the last price you rendered to trigger the flash,
  // and append to the sparkline buffer. Tickers missing from the payload were removed.
};
es.onerror = () => { /* EventSource reconnects automatically; show "reconnecting" */ };
```

The frontend should flash by comparing against the **last price it rendered**, not by trusting `direction` alone. The server samples the cache every 500ms, so the sample can occasionally skip a tick.

## 9. Tests

These pass against the prototype (`uv run pytest`, with `pytest-asyncio` in `asyncio_mode = "auto"`). The Massive client is mocked by replacing `source._client`, so no network or key is needed.

```python
import asyncio
import random
from types import SimpleNamespace
from unittest.mock import MagicMock

from massive.exceptions import BadResponse

from app.services.market import PriceCache, create_market_data_source
from app.services.market.massive import MassiveDataSource, snapshot_price
from app.services.market.simulator import GBMSimulator, SimulatorDataSource


def test_cache_tracks_previous_price_and_direction():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    update = cache.update("AAPL", 191.234)
    assert update.price == 191.23
    assert update.previous_price == 190.0
    assert update.prev_close == 190.0
    assert update.direction == "up"
    assert cache.version == 2


def test_factory_selects_source(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)
    monkeypatch.setenv("MASSIVE_API_KEY", "   ")
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)
    monkeypatch.setenv("MASSIVE_API_KEY", "abc")
    assert isinstance(create_market_data_source(PriceCache()), MassiveDataSource)


def test_simulator_is_deterministic_with_seed():
    a = GBMSimulator(rng=random.Random(1))
    b = GBMSimulator(rng=random.Random(1))
    for sim in (a, b):
        sim.add("AAPL")
        sim.add("PYPL")
    assert [a.step() for _ in range(5)] == [b.step() for _ in range(5)]


async def test_simulator_source_writes_ticks():
    cache = PriceCache()
    source = SimulatorDataSource(cache, tick_seconds=0.01)
    await source.start(["AAPL", "MSFT"])
    assert cache.get_price("AAPL") == 190.0
    await asyncio.sleep(0.05)
    assert cache.version > 2
    source.add_ticker("PYPL")
    assert cache.get_price("PYPL") is not None
    source.remove_ticker("MSFT")
    assert cache.get("MSFT") is None
    await source.stop()


def snap(ticker, last=None, minute=None, day=None, prev=None):
    obj = lambda v: SimpleNamespace(price=v, close=v) if v is not None else None
    return SimpleNamespace(ticker=ticker, last_trade=obj(last), min=obj(minute), day=obj(day), prev_day=obj(prev))


def test_snapshot_price_fallback_order():
    assert snapshot_price(snap("A", last=10, minute=9, day=8, prev=7)) == 10
    assert snapshot_price(snap("A", minute=9, day=8, prev=7)) == 9
    assert snapshot_price(snap("A", minute=0, day=0, prev=7)) == 7
    assert snapshot_price(snap("A")) is None


async def test_massive_snapshot_poll():
    cache = PriceCache()
    source = MassiveDataSource(cache, api_key="test")
    source._client = MagicMock()
    source._client.get_snapshot_all.return_value = [snap("AAPL", last=191.5, prev=189.0)]
    await source.start(["AAPL"])
    source._client.get_snapshot_all.assert_called_once_with("stocks", tickers=["AAPL"])
    assert cache.get("AAPL").price == 191.5
    assert cache.get("AAPL").prev_close == 189.0
    await source.stop()


async def test_massive_falls_back_to_eod_on_free_plan():
    cache = PriceCache()
    source = MassiveDataSource(cache, api_key="test")
    source._client = MagicMock()
    source._client.get_snapshot_all.side_effect = BadResponse(
        '{"status":"NOT_AUTHORIZED","message":"You are not entitled to this data."}'
    )
    bars = {
        0: [],  # today: no data yet
        1: [SimpleNamespace(ticker="AAPL", close=192.0), SimpleNamespace(ticker="MSFT", close=420.0)],
        2: [],  # weekend
        3: [SimpleNamespace(ticker="AAPL", close=190.0), SimpleNamespace(ticker="MSFT", close=415.0)],
    }
    calls = iter(range(10))
    source._client.get_grouped_daily_aggs.side_effect = lambda day: bars.get(next(calls), [])
    await source.start(["AAPL"])
    assert source._eod_mode
    assert cache.get("AAPL").price == 192.0
    assert cache.get("AAPL").prev_close == 190.0
    source.add_ticker("MSFT")  # served from stored EOD data, no extra API call
    assert cache.get("MSFT").price == 420.0
    await source.stop()


async def test_massive_logs_and_continues_on_other_errors():
    cache = PriceCache()
    source = MassiveDataSource(cache, api_key="test")
    source._client = MagicMock()
    source._client.get_snapshot_all.side_effect = BadResponse('{"status":"ERROR","error":"Unknown API Key"}')
    await source.start(["AAPL"])
    assert not source._eod_mode
    assert cache.get("AAPL") is None
    await source.stop()
```

## 10. Decisions

| Decision                                   | Why                                                                                           |
| ------------------------------------------ | --------------------------------------------------------------------------------------------- |
| Sources push into a cache; readers never call sources | Matches PLAN.md §6. SSE, trades and valuation all read the same prices, and the cache can serve many users later. |
| Snapshot endpoint, not per-ticker calls    | One call per poll, so the free plan's 5/min limit and request costs don't depend on watchlist size. |
| Free plan falls back to EOD automatically   | Snapshots are not on the free plan. Without a fallback, a free key would show no prices at all. |
| SSE sends the full state each time         | Tiny payload (about 20 tickers). A reconnecting client is correct after one event. No diffing logic needed. |
| Sync `add_ticker`/`remove_ticker`          | They only change in-memory state. Prices arrive on the next tick or poll.                     |
| No lock on the cache                        | Every write happens on the event loop thread.                                                 |
