# Market Data Backend: Detailed Design

The implementation spec for FinAlly's market data subsystem (PLAN.md §6): one interface, two price sources (a GBM simulator and the Massive REST API), one shared price cache, and the SSE stream that pushes prices to the browser. It contains the complete code for every module, how the rest of the backend uses it, and the test suite.

**How it relates to the other planning docs.** This document merges [MARKET_INTERFACE.md](MARKET_INTERFACE.md) and [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md) into one buildable design and **supersedes their code where they differ**. §14 lists every change and why. [MASSIVE_API.md](MASSIVE_API.md) remains the reference for Massive endpoints, plans and the Python client, and MARKET_SIMULATOR.md for the simulator's derivations.

**Status: implemented, and the code is now the source of truth.** The modules and tests live in `backend/` and were then hardened after the code review ([MARKET_DATA_REVIEW.md](MARKET_DATA_REVIEW.md)). The code blocks in this document and Appendix A show the first implementation (PR #5); they do **not** include the review fixes, which §16 summarizes. When this document and the code disagree, the code is right. Read the prose here for intent and contracts.

**Verification.** All code here was run, not just written, on Python 3.12 with FastAPI 0.142.2 and massive 2.8.0:

- The 57 tests in Appendix A pass with no network or API key. Each fix in §14 (F1–F6) was mutation-checked: putting the old behavior back makes its test fail.
- The Massive source was driven through the real `RESTClient` over HTTP against a fake server answering as the Starter and the free plan would.
- The SSE endpoint was checked under uvicorn with curl.
- The code blocks were extracted from this document and the suite re-run against them.

Contents: 1 Requirements · 2 Architecture · 3 Module layout · 4 Data model · 5 Price cache · 6 Ticker symbols · 7 Interface · 8 Factory · 9 Simulator · 10 Massive source · 11 FastAPI integration · 12 Testing · 13 Implementation checklist · 14 Changes from the earlier drafts · 15 Known limitations · 16 Changes after the code review · Appendix A Test suite

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
| R9  | Unit tests: GBM math, Massive parsing, both sources honor the interface (PLAN §12)                                                      | Appendix A                                 |

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

`app` is the backend's Python package (a placeholder name, as in MARKET_INTERFACE.md). Market data is service-layer code with its own package. The lifespan, a dependencies module and the SSE route wire it into the app. Other services only read the cache and call `add_ticker` / `sync_tickers` (§11.6).

```
backend/
  pyproject.toml
  app/
    __init__.py              # empty
    main.py                  # lifespan creates, starts and stops the source (§11.1)
    dependencies.py          # PriceCacheDep, MarketSourceDep (§11.2)
    routes/
      __init__.py            # empty
      stream.py              # GET /api/stream/prices (§11.3)
    services/
      __init__.py            # empty
      market/
        __init__.py          # public API
        models.py            # PriceUpdate (§4)
        cache.py             # PriceCache (§5)
        tickers.py           # normalize_ticker (§6)
        base.py              # MarketDataSource (§7)
        factory.py           # create_market_data_source (§8)
        simulator.py         # GBMSimulator, SimulatorDataSource (§9)
        massive.py           # MassiveDataSource (§10)
  tests/
    services/market/         # test_cache.py, test_interface.py, test_simulator.py, test_massive.py
    routes/                  # test_stream.py
```

Dependencies, from `backend/`:

```bash
uv add fastapi uvicorn massive    # fastapi 0.135+ has fastapi.sse; massive brings urllib3 and certifi
uv add --dev pytest pytest-asyncio httpx
```

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"   # async test functions run without decorators
pythonpath = ["."]      # lets tests import app
testpaths = ["tests"]
```

The package's public API:

**`backend/app/services/market/__init__.py`**

```python
"""Market data: one interface, two sources (simulator, Massive), one shared price cache."""

from .base import MarketDataSource
from .cache import PriceCache
from .factory import create_market_data_source
from .models import PriceUpdate
from .tickers import normalize_ticker

__all__ = [
    "MarketDataSource",
    "PriceCache",
    "PriceUpdate",
    "create_market_data_source",
    "normalize_ticker",
]
```

Everything outside the package imports from `app.services.market`. Only the factory and the tests import `SimulatorDataSource` or `MassiveDataSource` directly.

## 4. Data Model — `models.py`

`PriceUpdate` is the one price record. It is stored in the cache, read by services, and serialized for SSE and REST.

**`backend/app/services/market/models.py`**

```python
from dataclasses import dataclass
from typing import Literal

Direction = Literal["up", "down", "flat"]


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
        return round(self.price - self.previous_price, 4)

    @property
    def direction(self) -> Direction:
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def day_change_percent(self) -> float:
        if not self.prev_close:
            return 0.0
        return round((self.price - self.prev_close) / self.prev_close * 100, 4)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "prev_close": self.prev_close,
            "change": self.change,
            "day_change_percent": self.day_change_percent,
            "direction": self.direction,
            "timestamp": round(self.timestamp, 3),
        }
```

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

**`backend/app/services/market/cache.py`**

```python
import asyncio
import math
import time

from .models import PriceUpdate


class PriceCache:
    """Latest price per ticker. Written by the market data source, read by everyone else.

    All reads and writes happen on the event loop thread, so no lock is needed.
    `version` goes up on every change; `wait_for_change()` lets readers such as
    the SSE stream sleep until there is something new.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._changed = asyncio.Event()
        self.version = 0

    def update(
        self,
        ticker: str,
        price: float,
        prev_close: float | None = None,
        timestamp: float | None = None,
    ) -> PriceUpdate:
        """Store a new price. The old price becomes previous_price."""
        if not (math.isfinite(price) and price > 0):
            raise ValueError(f"Invalid price for {ticker}: {price!r}")
        old = self._prices.get(ticker)
        price = round(price, 2)
        if prev_close is None:
            prev_close = old.prev_close if old else price
        update = PriceUpdate(
            ticker=ticker,
            price=price,
            previous_price=old.price if old else price,
            prev_close=round(prev_close, 2),
            timestamp=time.time() if timestamp is None else timestamp,
        )
        self._prices[ticker] = update
        self._bump()
        return update

    def get(self, ticker: str) -> PriceUpdate | None:
        return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        update = self._prices.get(ticker)
        return update.price if update else None

    def all(self) -> dict[str, PriceUpdate]:
        return dict(self._prices)

    def remove(self, ticker: str) -> None:
        if self._prices.pop(ticker, None) is not None:
            self._bump()

    async def wait_for_change(self, version: int) -> int:
        """Return the current version as soon as it differs from `version`."""
        if self.version == version:
            await self._changed.wait()
        return self.version

    def _bump(self) -> None:
        self.version += 1
        self._changed.set()  # wake everyone waiting on the old event...
        self._changed = asyncio.Event()  # ...and give later waiters a fresh one
```

- **`update()`** rounds to cents (4 decimals below $1, so sub-dollar stocks keep their precision) and makes the old price the new `previous_price`. When `prev_close` is not given, or is unusable (zero, negative, NaN, infinity), the stored one carries forward (the first update uses its own price).
- **Invalid prices raise `ValueError`** (zero, negative, NaN, infinity), checked **after** rounding, so a positive price that rounds to 0 is rejected too. Neither source produces them in normal operation, but one NaN would serialize as `NaN`, which `JSON.parse` rejects, breaking the stream for every client.
- **`version`** goes up on every change. `wait_for_change(v)` returns as soon as `version != v`. Each change sets the current `asyncio.Event`, waking every waiter, and swaps in a fresh one. Setting an event is synchronous, so `update()` stays a plain method that sources can call in a loop. Waiters only run once the writer yields, so a simulator tick that updates ten tickers wakes the SSE stream once, after the whole tick.

## 6. Ticker Symbols — `tickers.py`

**`backend/app/services/market/tickers.py`**

```python
import re

# 1-7 letters/digits starting with a letter, plus an optional share-class suffix: AAPL, V, BRK.B, BF-B
_TICKER = re.compile(r"[A-Z][A-Z0-9]{0,6}(?:[.-][A-Z0-9]{1,3})?")


def normalize_ticker(raw: str) -> str:
    """Upper-case and validate a ticker symbol: ' brk.b ' -> 'BRK.B'. Raises ValueError if invalid."""
    ticker = raw.strip().upper()
    if not _TICKER.fullmatch(ticker):
        raise ValueError(f"Invalid ticker symbol: {raw!r}")
    return ticker
```

Call `normalize_ticker` wherever a ticker enters from outside: request bodies, path parameters, and tickers in the LLM's structured output. Answer `ValueError` with HTTP 422 (§11.6). The sources assume normalized input. Massive tickers are case-sensitive (`aapl` matches nothing), and without this check the simulator would invent a price for `HELLO WORLD`.

## 7. The Interface — `base.py`

**`backend/app/services/market/base.py`**

```python
from abc import ABC, abstractmethod
from collections.abc import Iterable


class MarketDataSource(ABC):
    """Produces prices for a set of tickers and writes them into a PriceCache.

    Tickers passed in must already be normalized (see normalize_ticker).
    """

    @abstractmethod
    async def start(self, tickers: Iterable[str]) -> None:
        """Price the given tickers, then keep them updated from a background task.

        When start() returns, every ticker that can be priced is in the cache.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task. Safe to call more than once."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start tracking a ticker and price it right away if possible. No-op if already tracked."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking a ticker and drop it from the cache. No-op if not tracked."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Tickers currently tracked, sorted."""

    def status(self) -> dict:
        """Small JSON-friendly summary for /api/health. Implementations add detail."""
        return {"source": type(self).__name__, "tickers": len(self.get_tickers())}

    async def sync_tickers(self, tickers: Iterable[str]) -> None:
        """Make the tracked set exactly `tickers`: add what is missing, remove the rest."""
        wanted = set(tickers)
        current = set(self.get_tickers())
        for ticker in sorted(current - wanted):
            await self.remove_ticker(ticker)
        for ticker in sorted(wanted - current):
            await self.add_ticker(ticker)
```

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

**`backend/app/services/market/factory.py`**

```python
import logging
import os

from .base import MarketDataSource
from .cache import PriceCache
from .massive import MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 15.0


def create_market_data_source(cache: PriceCache) -> MarketDataSource:
    """Massive if MASSIVE_API_KEY is set and non-empty, otherwise the simulator."""
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not api_key:
        logger.info("Market data: built-in simulator")
        return SimulatorDataSource(cache)
    poll_seconds = _poll_seconds()
    logger.info("Market data: Massive API, polling every %.0fs", poll_seconds)
    return MassiveDataSource(cache, api_key, poll_seconds=poll_seconds)


def _poll_seconds() -> float:
    raw = os.environ.get("MASSIVE_POLL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_POLL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if not value >= 1:  # also rejects nan
        logger.warning("Ignoring MASSIVE_POLL_SECONDS=%r (need a number >= 1)", raw)
        return DEFAULT_POLL_SECONDS
    return value
```

| Env var                | Default | Effect                                                                                                                                                                                                                                                                                           |
| ---------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `MASSIVE_API_KEY`      | empty   | Non-empty → Massive; empty or whitespace → simulator                                                                                                                                                                                                                                             |
| `MASSIVE_POLL_SECONDS` | `15`    | Snapshot poll interval, at least 1, and the base of the retry backoff. Starter plans and up have unlimited calls, so 2–5 is fine. EOD mode refreshes hourly and retries at most once a minute, so a low value left over after a downgrade is safe. Bad values log a warning and fall back to 15. |

Add `MASSIVE_POLL_SECONDS=` to `.env.example` as optional. The factory reads `os.environ` when it runs, so `.env` must already be loaded: Docker's `--env-file` does this; locally, use `uv run --env-file ../.env ...`.

## 9. Simulator — `simulator.py`

### 9.1 Model

The math is unchanged from MARKET_SIMULATOR.md, which has the derivations.

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

### 9.3 Code

`GBMSimulator` does the math with no asyncio or I/O, so it is easy to test. `SimulatorDataSource` wraps it in a background task and implements `MarketDataSource`.

**`backend/app/services/market/simulator.py`**

```python
import asyncio
import logging
import math
import random
import zlib
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass

from .base import MarketDataSource
from .cache import PriceCache

logger = logging.getLogger(__name__)

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600


@dataclass(frozen=True, slots=True)
class TickerProfile:
    """Simulation parameters for one ticker. Volatility and drift are annualized."""

    seed_price: float
    volatility: float
    drift: float
    sector: str


PROFILES: dict[str, TickerProfile] = {
    "AAPL": TickerProfile(190.0, 0.25, 0.08, "tech"),
    "GOOGL": TickerProfile(175.0, 0.30, 0.08, "tech"),
    "MSFT": TickerProfile(420.0, 0.25, 0.08, "tech"),
    "AMZN": TickerProfile(185.0, 0.32, 0.08, "tech"),
    "NVDA": TickerProfile(130.0, 0.50, 0.12, "tech"),
    "META": TickerProfile(500.0, 0.40, 0.08, "tech"),
    "TSLA": TickerProfile(250.0, 0.60, 0.05, "auto"),
    "NFLX": TickerProfile(650.0, 0.40, 0.08, "media"),
    "JPM": TickerProfile(200.0, 0.22, 0.06, "finance"),
    "V": TickerProfile(280.0, 0.20, 0.06, "finance"),
}


def profile_for(ticker: str) -> TickerProfile:
    """Known profile, or a deterministic default ($50-$300, own sector) for any other ticker."""
    if ticker in PROFILES:
        return PROFILES[ticker]
    seed_price = 50.0 + zlib.crc32(ticker.encode()) % 25000 / 100
    return TickerProfile(seed_price, volatility=0.30, drift=0.08, sector=ticker)


class GBMSimulator:
    """Correlated geometric Brownian motion with occasional jump events. Pure math, no I/O."""

    def __init__(
        self,
        tick_seconds: float = 0.5,
        time_scale: float = 20.0,
        market_weight: float = 0.3,
        sector_weight: float = 0.3,
        event_probability: float = 0.0005,
        rng: random.Random | None = None,
    ) -> None:
        if min(market_weight, sector_weight) < 0 or market_weight + sector_weight > 1:
            raise ValueError("market_weight and sector_weight must be >= 0 and sum to at most 1")
        self.dt = tick_seconds * time_scale / TRADING_SECONDS_PER_YEAR
        self._sqrt_dt = math.sqrt(self.dt)
        self._market_w = math.sqrt(market_weight)
        self._sector_w = math.sqrt(sector_weight)
        self._own_w = math.sqrt(1.0 - market_weight - sector_weight)
        self._event_probability = event_probability
        self._rng = rng or random.Random()
        self._profiles: dict[str, TickerProfile] = {}
        self._prices: dict[str, float] = {}  # tickers being simulated
        self._parked: dict[str, float] = {}  # last price of removed tickers

    def __contains__(self, ticker: str) -> bool:
        return ticker in self._prices

    def add(self, ticker: str) -> float:
        """Start simulating a ticker (resuming its last price if it was removed); return the price."""
        if ticker not in self._prices:
            profile = self._profiles.setdefault(ticker, profile_for(ticker))
            self._prices[ticker] = self._parked.pop(ticker, profile.seed_price)
        return self._prices[ticker]

    def remove(self, ticker: str) -> None:
        if ticker in self._prices:
            self._parked[ticker] = self._prices.pop(ticker)

    def tickers(self) -> list[str]:
        return list(self._prices)

    def reference_price(self, ticker: str) -> float:
        """Stand-in for the previous close: the seed price."""
        return self._profiles[ticker].seed_price

    def step(self) -> dict[str, float]:
        """Advance every ticker by one tick and return the new (unrounded) prices."""
        rng = self._rng
        market = rng.gauss(0.0, 1.0)
        sectors: dict[str, float] = {}
        for ticker, price in list(self._prices.items()):
            p = self._profiles[ticker]
            if p.sector not in sectors:
                sectors[p.sector] = rng.gauss(0.0, 1.0)
            z = (
                self._market_w * market
                + self._sector_w * sectors[p.sector]
                + self._own_w * rng.gauss(0.0, 1.0)
            )
            log_return = (p.drift - 0.5 * p.volatility**2) * self.dt + p.volatility * self._sqrt_dt * z
            if rng.random() < self._event_probability:
                log_return += math.log1p(rng.choice((-1, 1)) * rng.uniform(0.02, 0.05))
            self._prices[ticker] = price * math.exp(log_return)
        return dict(self._prices)


class SimulatorDataSource(MarketDataSource):
    """Runs GBMSimulator in a background task and writes every tick into the cache."""

    def __init__(
        self,
        cache: PriceCache,
        tick_seconds: float = 0.5,
        simulator: GBMSimulator | None = None,
    ) -> None:
        self._cache = cache
        self._tick_seconds = tick_seconds
        self._sim = simulator or GBMSimulator(tick_seconds=tick_seconds)
        self._task: asyncio.Task | None = None

    async def start(self, tickers: Iterable[str]) -> None:
        for ticker in tickers:
            await self.add_ticker(ticker)
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="market-simulator")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def add_ticker(self, ticker: str) -> None:
        if ticker not in self._sim:
            self._write(ticker, self._sim.add(ticker))

    async def remove_ticker(self, ticker: str) -> None:
        self._sim.remove(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self._sim.tickers())

    def status(self) -> dict:
        return {"source": "simulator", "tickers": len(self._sim.tickers())}

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._tick_seconds)
            try:
                for ticker, price in self._sim.step().items():
                    self._write(ticker, price)
            except Exception:
                logger.exception("Simulator tick failed")

    def _write(self, ticker: str, price: float) -> None:
        self._cache.update(ticker, price, prev_close=self._sim.reference_price(ticker))
```

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

### 10.3 Code

**`backend/app/services/market/massive.py`**

```python
import asyncio
import json
import logging
import time
from collections.abc import Iterable, Sequence
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta

from massive import RESTClient
from massive.exceptions import BadResponse
from massive.rest.models import TickerSnapshot
from urllib3.exceptions import HTTPError

from .base import MarketDataSource
from .cache import PriceCache

logger = logging.getLogger(__name__)

EOD_POLL_SECONDS = 3600.0  # free plan: closes change once a day
EOD_MIN_RETRY_SECONDS = 60.0  # free plan: 5 calls/min, so retry at most once a minute
MAX_BACKOFF_SECONDS = 300.0  # longest wait between attempts after repeated failures
MAX_EOD_LOOKUPS = 4  # grouped-daily calls per EOD refresh; the free plan allows 5 calls/min


class EndOfDayDataMissing(Exception):
    """No grouped daily bars were found for any recent trading day."""


def snapshot_price(snap: TickerSnapshot) -> float | None:
    """Best available price: last trade, then minute bar, then day bar, then previous close."""
    candidates = (
        snap.last_trade.price if snap.last_trade else None,
        snap.min.close if snap.min else None,
        snap.day.close if snap.day else None,
        snap.prev_day.close if snap.prev_day else None,
    )
    return next((p for p in candidates if p and p > 0), None)


def is_not_authorized(error: BadResponse) -> bool:
    """True when the key's plan does not include the requested data (HTTP 403 NOT_AUTHORIZED)."""
    try:
        body = json.loads(str(error))
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    message = str(body.get("message") or body.get("error") or "").lower()
    return body.get("status") == "NOT_AUTHORIZED" or "not entitled" in message


def us_market_today() -> date:
    """Today's date in New York, approximated as UTC-5 (never ahead of the real date)."""
    return (datetime.now(UTC) - timedelta(hours=5)).date()


class MassiveDataSource(MarketDataSource):
    """Polls the Massive REST API and writes prices into the cache.

    Snapshot mode (Starter plan and up): one Full Market Snapshot call per poll covers
    every tracked ticker. EOD mode (free Basic plan, detected from the first 403):
    closing prices from the grouped daily endpoint, refreshed hourly.
    """

    def __init__(
        self,
        cache: PriceCache,
        api_key: str,
        poll_seconds: float = 15.0,
        client: RESTClient | None = None,
    ) -> None:
        self._cache = cache
        # retries=0: the poll loop is the retry policy. The client's own retries obey
        # Retry-After on 429s, which can block a worker thread for minutes.
        self._client = client or RESTClient(
            api_key=api_key, connect_timeout=5.0, read_timeout=10.0, retries=0
        )
        self._poll_seconds = poll_seconds
        self._tickers: set[str] = set()
        self._eod_mode = False
        self._eod_closes: dict[str, tuple[float, float]] = {}  # ticker -> (close, previous close)
        self._failures = 0
        self._last_success: float | None = None
        self._last_error: str | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: Iterable[str]) -> None:
        self._tickers.update(tickers)
        await self._refresh()
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="massive-poller")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:
            return
        self._tickers.add(ticker)
        if self._eod_mode:
            self._write_eod(ticker)  # from the stored EOD data, no API call
        else:
            await self._refresh([ticker])  # one snapshot call, so the price is there right away

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self._tickers)

    def status(self) -> dict:
        return {
            "source": "massive",
            "mode": "eod" if self._eod_mode else "snapshot",
            "tickers": len(self._tickers),
            "last_success": self._last_success,
            "last_error": self._last_error,
        }

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._next_delay())
            await self._refresh()

    def _next_delay(self) -> float:
        if not self._failures:
            return EOD_POLL_SECONDS if self._eod_mode else self._poll_seconds
        delay = min(self._poll_seconds * 2**self._failures, MAX_BACKOFF_SECONDS)
        if self._eod_mode:  # also covers a low MASSIVE_POLL_SECONDS left over from a paid plan
            delay = max(delay, EOD_MIN_RETRY_SECONDS)
        return delay

    async def _refresh(self, tickers: Sequence[str] | None = None) -> None:
        """Poll once. Failures are logged and counted, never raised, so the loop never dies."""
        try:
            if self._eod_mode:
                await self._poll_eod()
            else:
                await self._poll_snapshot(self.get_tickers() if tickers is None else tickers)
        except BadResponse as e:
            if not self._eod_mode and is_not_authorized(e):
                logger.warning("Massive plan has no snapshot access; using end-of-day prices")
                self._eod_mode = True
                await self._refresh()
                return
            self._record_failure(f"Massive API error: {e}")
        except (HTTPError, EndOfDayDataMissing) as e:  # HTTPError: network, timeout, 429/5xx
            self._record_failure(f"Massive request failed: {e}")
        except Exception as e:
            logger.exception("Unexpected error while polling Massive")
            self._record_failure(f"Unexpected error: {e!r}")
        else:
            self._record_success()

    async def _poll_snapshot(self, tickers: Sequence[str]) -> None:
        if not tickers:
            return
        snapshots = await asyncio.to_thread(
            self._client.get_snapshot_all, "stocks", tickers=list(tickers)
        )
        for snap in snapshots:
            price = snapshot_price(snap)
            if price is None or snap.ticker not in self._tickers:
                continue  # no usable price, or removed while the request was in flight
            prev_close = snap.prev_day.close if snap.prev_day and snap.prev_day.close else None
            self._cache.update(snap.ticker, price, prev_close=prev_close)

    async def _poll_eod(self) -> None:
        sessions = await asyncio.to_thread(self._recent_closes)
        if not sessions:
            raise EndOfDayDataMissing("no grouped daily bars for recent trading days")
        latest, previous = sessions[0], sessions[-1]
        self._eod_closes = {t: (close, previous.get(t, close)) for t, close in latest.items()}
        for ticker in self._tickers:
            self._write_eod(ticker)

    def _recent_closes(self) -> list[dict[str, float]]:
        """Closes for the two most recent finished trading days, newest first. Runs in a thread.

        Starts at yesterday (New York time) because the free plan only has a day's bars
        after it ends. Weekends are skipped without a call, and at most MAX_EOD_LOOKUPS
        calls are made, so a refresh fits the free plan's 5 calls/min.
        """
        sessions: list[dict[str, float]] = []
        day = us_market_today()
        lookups = 0
        while len(sessions) < 2 and lookups < MAX_EOD_LOOKUPS:
            day -= timedelta(days=1)
            if day.weekday() >= 5:  # Saturday or Sunday
                continue
            lookups += 1
            try:
                aggs = self._client.get_grouped_daily_aggs(day.isoformat())
            except BadResponse as e:
                if is_not_authorized(e):
                    continue  # this day is not available on the plan (yet)
                raise
            closes = {a.ticker: a.close for a in aggs if a.ticker and a.close}
            if closes:  # empty on market holidays
                sessions.append(closes)
        return sessions

    def _write_eod(self, ticker: str) -> None:
        if ticker in self._eod_closes:
            close, prev_close = self._eod_closes[ticker]
            self._cache.update(ticker, close, prev_close=prev_close)

    def _record_success(self) -> None:
        if self._failures:
            logger.info("Massive polling recovered after %d failed attempt(s)", self._failures)
        self._failures = 0
        self._last_success = time.time()
        self._last_error = None

    def _record_failure(self, message: str) -> None:
        self._failures += 1
        self._last_error = message
        logger.error("%s (attempt %d, next try in %.0fs)", message, self._failures, self._next_delay())
```

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

The market data parts of `backend/app/main.py`. `init_db` and `tracked_tickers` belong to the database layer (§11.5):

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db, tracked_tickers  # database layer
from app.routes import stream
from app.services.market import PriceCache, create_market_data_source


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # create tables and seed data if missing
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(tracked_tickers())  # watchlist ∪ open positions
    app.state.price_cache = cache
    app.state.market_source = source
    try:
        yield
    finally:
        await source.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(stream.router)
```

Run a **single uvicorn worker** (the default). The cache and simulator live in process memory, so each extra worker would run its own simulator and show different prices.

Run uvicorn with **`--timeout-graceful-shutdown 2`**, for example `uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 2` as the Docker `CMD`. SSE streams never end on their own, and on SIGTERM uvicorn waits for open connections before it runs the lifespan shutdown, with no timeout by default. Without the flag, a shutdown with any browser tab open hangs until the tab closes: `docker stop` ends in SIGKILL after 10s and `--reload` stalls. With it, open streams are cancelled after 2s and the lifespan shutdown still runs. `test_graceful_shutdown_timeout_closes_open_streams` covers this.

`main.py` calls `logging.basicConfig(level=INFO)`. uvicorn configures only its own loggers, so without it the app's INFO lines (which source is running, polling recovered) never appear.

### 11.2 Dependencies — `dependencies.py`

**`backend/app/dependencies.py`**

```python
from typing import Annotated

from fastapi import Depends, Request

from app.services.market import MarketDataSource, PriceCache


def get_price_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache


def get_market_source(request: Request) -> MarketDataSource:
    return request.app.state.market_source


PriceCacheDep = Annotated[PriceCache, Depends(get_price_cache)]
MarketSourceDep = Annotated[MarketDataSource, Depends(get_market_source)]
```

### 11.3 SSE Endpoint — `routes/stream.py`

**`backend/app/routes/stream.py`**

```python
from collections.abc import AsyncIterable

from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.dependencies import PriceCacheDep

router = APIRouter()

RECONNECT_MS = 1000  # how long the browser waits before reconnecting a dropped stream


@router.get("/api/stream/prices", response_class=EventSourceResponse)
async def stream_prices(cache: PriceCacheDep) -> AsyncIterable[ServerSentEvent]:
    """Every tracked ticker's price on connect, then again after each cache change."""
    version = -1  # never equal to cache.version, so the first event goes out immediately
    retry: int | None = RECONNECT_MS  # sent once; the browser remembers it
    while True:
        version = await cache.wait_for_change(version)
        yield ServerSentEvent(data={t: u.to_dict() for t, u in cache.all().items()}, retry=retry)
        retry = None
```

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
uv run pytest    # 76 tests in about 3s; no network or API key needed
uv run ruff check app tests && uv run ruff format --check app tests && uv run mypy app
```

| File                | Covers                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_cache.py`     | previous price, direction and rounding (4 decimals below $1, validated after rounding); unusable `prev_close` carrying forward; `prev_close` carry-forward; invalid prices; `version`; the SSE dict shape; `wait_for_change` (immediate return, wake-up on change)                                                                                                                                                                                                                      |
| `test_interface.py` | `normalize_ticker`; factory selection and `MASSIVE_POLL_SECONDS` parsing; `sync_tickers`                                                                                                                                                                                                                                                                                                        |
| `test_simulator.py` | unknown-ticker profiles; determinism with a seed; parked prices, and `prev_close` staying at the seed after a re-add; a failing tick; one task after a second `start()`; idempotent `add_ticker`; volatility and correlations against the model (20k ticks, fixed seed); jump rate; source start, add, remove and stop                                                                                                                                                                                                           |
| `test_massive.py`   | no hidden client retries; snapshot price fallback; 403 detection; one call per poll; immediate pricing on add; the in-flight removal race; free-plan EOD fallback (exact call sequence); holidays and 403 days; a single EOD session; the lookup cap; backoff and recovery; a downgrade while running; the free plan's one-minute retry floor; the loop surviving network and unexpected errors; `add_ticker` waiting at most 3s and making no call while failing; `sync_tickers` batching; a downgrade with concurrent adds; one poller after a second `start()`; `us_market_today()` |
| `test_stream.py`    | real uvicorn and httpx: headers, `retry`, full state on connect, an event per change, removed tickers dropping out; shutdown with a client attached under `timeout_graceful_shutdown` |
| `test_main.py`      | the lifespan starts the simulator and `/api/health` reports it; the source stops on shutdown |

The Massive tests pass a `FakeClient` through the `client=` parameter, so they need no network. The statistical tests use fixed seeds and are deterministic. The full suite is in Appendix A.

Manual check:

```bash
uv run uvicorn app.main:app --port 8000 --timeout-graceful-shutdown 2
curl -N localhost:8000/api/stream/prices    # an event every 0.5s with the simulator
curl localhost:8000/api/health
```

## 13. Implementation Checklist

1. Add the dependencies and the pytest settings (§3).
2. Create `services/market/` in dependency order: `models.py`, `cache.py`, `tickers.py`, `base.py`, `simulator.py`, `massive.py`, `factory.py`, `__init__.py`.
3. Add the tests (Appendix A). `uv run pytest` must pass before wiring anything else.
4. Add `dependencies.py`, `routes/stream.py`, the lifespan in `main.py`, and `market_data` in `/api/health` (§11).
5. Add `tracked_tickers()` to the database layer (§11.5), and call `sync_tickers` / `add_ticker` from the watchlist routes, trade execution and the chat flow (§11.6).
6. Apply `normalize_ticker` wherever a ticker enters from outside.
7. Add `MASSIVE_POLL_SECONDS=` to `.env.example`.
8. Check by hand with `curl -N` (§12). With a Massive key, `/api/health` should show the expected `mode` and no `last_error`.

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

From [MARKET_DATA_REVIEW.md](MARKET_DATA_REVIEW.md). The code in `backend/` has these; the code blocks above do not.

| #   | Problem                                                                                                         | Change                                                                                                                                 |
| --- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | A shutdown with any SSE client attached hung until the client left                                               | Run uvicorn with `--timeout-graceful-shutdown 2` (§11.1, PLAN.md §11); covered by a test                                               |
| M2  | On Massive, each new ticker could hold up a request for the 10s read timeout while the API was down               | `add_ticker`/`sync_tickers` make one batched call, wait at most 3s, and make no call while the API is failing (§10.5)                  |
| L1  | The cache validated before rounding (a sub-cent price became 0.0) and never checked `prev_close` (NaN broke the SSE JSON) | Round first (4 decimals below $1), then validate; an unusable `prev_close` carries the stored one forward (§5)                         |
| L2  | Concurrent refreshes during a plan downgrade could burst past the free plan's 5 calls/min                        | `asyncio.Lock` around `_refresh`; the downgrade switches to EOD once (§10.5)                                                            |
| L3  | The app's INFO logs never appeared under uvicorn                                                                 | `logging.basicConfig(level=INFO)` in `main.py` (§11.1)                                                                                 |
| T   | Behaviors without tests                                                                                          | 19 new tests (76 in all), including the lifespan and `/api/health`; all 11 mutation spot-checks in the review are now caught           |
| N   | No lint, format or type-check config                                                                             | `ruff` (line length 120) and `mypy` in the dev group and configured in `pyproject.toml`; all clean                                      |

## Appendix A. Test Suite

**`backend/tests/services/market/test_cache.py`**

```python
import asyncio

import pytest

from app.services.market import PriceCache, PriceUpdate


def test_update_tracks_previous_price_and_direction():
    cache = PriceCache()
    first = cache.update("AAPL", 190.0)
    assert (first.price, first.previous_price, first.direction) == (190.0, 190.0, "flat")
    second = cache.update("AAPL", 191.234)
    assert second.price == 191.23  # rounded to cents
    assert second.previous_price == 190.0
    assert second.direction == "up"
    assert cache.update("AAPL", 190.5).direction == "down"
    assert cache.version == 3


def test_prev_close_defaults_to_first_price_then_carries_forward():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    assert cache.update("AAPL", 195.0).prev_close == 190.0
    assert cache.update("AAPL", 196.0, prev_close=193.0).prev_close == 193.0
    assert cache.update("AAPL", 197.0).prev_close == 193.0


@pytest.mark.parametrize("bad", [0, -1.0, float("nan"), float("inf")])
def test_rejects_invalid_prices(bad):
    with pytest.raises(ValueError):
        PriceCache().update("AAPL", bad)


def test_remove_bumps_version_only_when_present():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.remove("MSFT")
    assert cache.version == 1
    cache.remove("AAPL")
    assert cache.version == 2
    assert cache.get("AAPL") is None
    assert cache.get_price("AAPL") is None


def test_to_dict_is_the_sse_contract():
    update = PriceUpdate("AAPL", price=189.95, previous_price=190.0, prev_close=190.0, timestamp=1.23456)
    assert update.to_dict() == {
        "ticker": "AAPL",
        "price": 189.95,
        "previous_price": 190.0,
        "prev_close": 190.0,
        "change": -0.05,
        "day_change_percent": -0.0263,
        "direction": "down",
        "timestamp": 1.235,
    }
    assert PriceUpdate("X", 1.0, 1.0, prev_close=0.0, timestamp=0).day_change_percent == 0.0


async def test_wait_for_change_returns_at_once_when_version_differs():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    assert await cache.wait_for_change(0) == 1


async def test_wait_for_change_wakes_on_update():
    cache = PriceCache()
    waiter = asyncio.create_task(cache.wait_for_change(cache.version))
    await asyncio.sleep(0)
    assert not waiter.done()
    cache.update("AAPL", 190.0)
    assert await asyncio.wait_for(waiter, 1) == 1
```

**`backend/tests/services/market/test_interface.py`**

```python
import pytest

from app.services.market import PriceCache, create_market_data_source, normalize_ticker
from app.services.market.massive import MassiveDataSource
from app.services.market.simulator import SimulatorDataSource


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("aapl", "AAPL"), (" brk.b ", "BRK.B"), ("V", "V"), ("bf-b", "BF-B"), ("GOOGL", "GOOGL")],
)
def test_normalize_ticker_accepts_symbols(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "1ABC", "AA PL", "$AAPL", "TOOLONGTICKER", "AAPL."])
def test_normalize_ticker_rejects_garbage(raw):
    with pytest.raises(ValueError):
        normalize_ticker(raw)


def test_factory_selects_source(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)
    monkeypatch.setenv("MASSIVE_API_KEY", "   ")
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)
    monkeypatch.setenv("MASSIVE_API_KEY", "abc")
    assert isinstance(create_market_data_source(PriceCache()), MassiveDataSource)


@pytest.mark.parametrize(("raw", "expected"), [("", 15.0), ("5", 5.0), ("0.2", 15.0), ("fast", 15.0)])
def test_factory_poll_seconds(monkeypatch, raw, expected):
    monkeypatch.setenv("MASSIVE_API_KEY", "abc")
    monkeypatch.setenv("MASSIVE_POLL_SECONDS", raw)
    assert create_market_data_source(PriceCache())._poll_seconds == expected


async def test_sync_tickers_adds_missing_and_removes_extra():
    cache = PriceCache()
    source = SimulatorDataSource(cache)
    await source.start(["AAPL", "MSFT"])
    await source.sync_tickers(["MSFT", "PYPL"])
    assert source.get_tickers() == ["MSFT", "PYPL"]
    assert cache.get("AAPL") is None
    assert cache.get_price("PYPL") is not None
    await source.stop()
```

**`backend/tests/services/market/test_simulator.py`**

```python
import asyncio
import math
import random
import statistics

import pytest

from app.services.market import PriceCache
from app.services.market.simulator import GBMSimulator, SimulatorDataSource, profile_for


def test_unknown_ticker_gets_stable_profile():
    p = profile_for("PYPL")
    assert p == profile_for("PYPL")
    assert 50 <= p.seed_price < 300
    assert (p.volatility, p.drift, p.sector) == (0.30, 0.08, "PYPL")


def test_rejects_weights_above_one():
    with pytest.raises(ValueError):
        GBMSimulator(market_weight=0.6, sector_weight=0.5)


def test_simulator_is_deterministic_with_seed():
    a = GBMSimulator(rng=random.Random(1))
    b = GBMSimulator(rng=random.Random(1))
    for sim in (a, b):
        sim.add("AAPL")
        sim.add("PYPL")
    assert [a.step() for _ in range(5)] == [b.step() for _ in range(5)]


def test_removed_ticker_resumes_its_last_price():
    sim = GBMSimulator(rng=random.Random(2))
    sim.add("AAPL")
    for _ in range(10):
        sim.step()
    last = sim.step()["AAPL"]
    sim.remove("AAPL")
    assert "AAPL" not in sim
    assert sim.add("AAPL") == last


def test_volatility_and_correlations_match_the_model():
    sim = GBMSimulator(event_probability=0.0, rng=random.Random(42))
    for t in ("AAPL", "MSFT", "JPM", "PYPL"):
        sim.add(t)
    prev = sim.step()
    returns: dict[str, list[float]] = {t: [] for t in prev}
    for _ in range(20_000):
        cur = sim.step()
        for t in cur:
            returns[t].append(math.log(cur[t] / prev[t]))
        prev = cur
    assert statistics.stdev(returns["AAPL"]) == pytest.approx(0.25 * math.sqrt(sim.dt), rel=0.03)
    assert statistics.correlation(returns["AAPL"], returns["MSFT"]) == pytest.approx(0.6, abs=0.03)  # same sector
    assert statistics.correlation(returns["AAPL"], returns["JPM"]) == pytest.approx(0.3, abs=0.03)  # market only
    assert statistics.correlation(returns["AAPL"], returns["PYPL"]) == pytest.approx(0.3, abs=0.03)  # unknown ticker


def test_jump_events_happen_at_the_configured_rate():
    sim = GBMSimulator(rng=random.Random(7))
    for t in ("AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"):
        sim.add(t)
    prev, jumps = sim.step(), 0
    for _ in range(20_000):
        cur = sim.step()
        jumps += sum(abs(math.log(cur[t] / prev[t])) > 0.015 for t in cur)  # diffusion alone is < 0.5%
        prev = cur
    assert 70 <= jumps <= 130  # expected 10 tickers x 20,000 ticks x 0.0005 = 100


async def test_source_seeds_on_start_then_ticks():
    cache = PriceCache()
    source = SimulatorDataSource(cache, tick_seconds=0.01)
    await source.start(["AAPL", "MSFT"])
    assert cache.get_price("AAPL") == 190.0  # priced before the first tick
    await asyncio.sleep(0.1)
    assert cache.version > 10
    assert cache.get("AAPL").prev_close == 190.0  # day change is measured from the seed price
    await source.stop()


async def test_source_add_and_remove_ticker():
    cache = PriceCache()
    source = SimulatorDataSource(cache, tick_seconds=0.01)
    await source.start(["AAPL"])
    await source.add_ticker("PYPL")
    assert cache.get_price("PYPL") == profile_for("PYPL").seed_price
    await asyncio.sleep(0.05)
    await source.remove_ticker("PYPL")
    assert cache.get("PYPL") is None
    assert source.get_tickers() == ["AAPL"]
    await source.stop()


async def test_stop_halts_ticks_and_is_idempotent():
    cache = PriceCache()
    source = SimulatorDataSource(cache, tick_seconds=0.01)
    await source.start(["AAPL"])
    await asyncio.sleep(0.03)
    await source.stop()
    await source.stop()
    version = cache.version
    await asyncio.sleep(0.03)
    assert cache.version == version
```

**`backend/tests/services/market/test_massive.py`**

```python
import asyncio
import threading
from datetime import date

import pytest
from massive.exceptions import BadResponse
from massive.rest.models import Agg, GroupedDailyAgg, LastTrade, MinuteSnapshot, TickerSnapshot
from urllib3.exceptions import MaxRetryError

from app.services.market import PriceCache
from app.services.market import massive as massive_module
from app.services.market.massive import (
    MAX_EOD_LOOKUPS,
    MassiveDataSource,
    is_not_authorized,
    snapshot_price,
)

NOT_AUTHORIZED = '{"status":"NOT_AUTHORIZED","request_id":"x","message":"You are not entitled to this data."}'


class FakeClient:
    """Stands in for massive.RESTClient: canned responses, and a log of every call."""

    def __init__(self, snapshots=(), grouped=None, snapshot_error=None):
        self.snapshots = {s.ticker: s for s in snapshots}
        self.grouped = grouped or {}  # "YYYY-MM-DD" -> bars, or an exception to raise
        self.snapshot_error = snapshot_error
        self.calls = []

    def get_snapshot_all(self, market_type, tickers):
        self.calls.append(("snapshot", *tickers))
        if self.snapshot_error:
            raise self.snapshot_error
        return [self.snapshots[t] for t in tickers if t in self.snapshots]

    def get_grouped_daily_aggs(self, day):
        self.calls.append(("grouped", day))
        result = self.grouped.get(day, [])
        if isinstance(result, Exception):
            raise result
        return result


def snap(ticker, last=None, minute=None, day=None, prev=None):
    return TickerSnapshot(
        ticker=ticker,
        last_trade=LastTrade(price=last) if last is not None else None,
        min=MinuteSnapshot(close=minute) if minute is not None else None,
        day=Agg(close=day) if day is not None else None,
        prev_day=Agg(close=prev) if prev is not None else None,
    )


def bars(**closes):
    return [GroupedDailyAgg(ticker=t, close=c) for t, c in closes.items()]


@pytest.fixture
def monday(monkeypatch):
    monkeypatch.setattr(massive_module, "us_market_today", lambda: date(2026, 10, 5))


def test_real_client_has_no_hidden_retries():
    # The client's own retries obey Retry-After on 429 and spend the free plan's calls.
    assert MassiveDataSource(PriceCache(), "key")._client.retries == 0


def test_snapshot_price_fallback_order():
    assert snapshot_price(snap("A", last=10, minute=9, day=8, prev=7)) == 10
    assert snapshot_price(snap("A", minute=9, day=8, prev=7)) == 9  # Starter plan: no last trade
    assert snapshot_price(snap("A", minute=0, day=0, prev=7)) == 7  # early morning: bars are reset
    assert snapshot_price(snap("A")) is None


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (NOT_AUTHORIZED, True),
        ('{"status":"ERROR","message":"You are not entitled to this data."}', True),
        ('{"status":"ERROR","request_id":"x","error":"Unknown API Key"}', False),
        ("<html>502 Bad Gateway</html>", False),
        ("null", False),
    ],
)
def test_is_not_authorized(body, expected):
    assert is_not_authorized(BadResponse(body)) is expected


async def test_start_polls_all_tickers_in_one_call():
    client = FakeClient([snap("AAPL", minute=191.5, prev=189.0), snap("MSFT", last=421.0, prev=420.0)])
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", client=client)
    await source.start(["MSFT", "AAPL", "XYZQ"])
    assert client.calls == [("snapshot", "AAPL", "MSFT", "XYZQ")]
    assert (cache.get("AAPL").price, cache.get("AAPL").prev_close) == (191.5, 189.0)
    assert cache.get("XYZQ") is None  # unknown tickers are left out of the response
    assert source.status()["mode"] == "snapshot"
    await source.stop()


async def test_add_ticker_is_priced_right_away():
    client = FakeClient([snap("AAPL", minute=191.5), snap("PYPL", minute=61.2, prev=60.0)])
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", client=client)
    await source.start(["AAPL"])
    await source.add_ticker("PYPL")
    await source.add_ticker("PYPL")  # already tracked: no call
    assert client.calls[1:] == [("snapshot", "PYPL")]
    assert cache.get_price("PYPL") == 61.2
    await source.stop()


async def test_ticker_removed_during_a_poll_is_not_written_back():
    class GatedClient(FakeClient):
        gate, waiting = threading.Event(), threading.Event()

        def get_snapshot_all(self, market_type, tickers):
            self.waiting.set()
            self.gate.wait(5)
            return super().get_snapshot_all(market_type, tickers)

    client = GatedClient([snap("AAPL", minute=191.5), snap("MSFT", minute=421.0)])
    client.gate.set()
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", poll_seconds=0.01, client=client)
    await source.start(["AAPL", "MSFT"])
    client.gate.clear()
    client.waiting.clear()
    await asyncio.to_thread(client.waiting.wait, 5)  # a background poll is now in flight
    await source.remove_ticker("MSFT")
    client.gate.set()
    await asyncio.sleep(0.05)
    assert cache.get("MSFT") is None
    assert cache.get_price("AAPL") == 191.5
    await source.stop()


async def test_free_plan_falls_back_to_end_of_day_prices(monday):
    client = FakeClient(
        snapshot_error=BadResponse(NOT_AUTHORIZED),
        grouped={"2026-10-02": bars(AAPL=192.0, MSFT=420.0), "2026-10-01": bars(AAPL=190.0, MSFT=415.0)},
    )
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", client=client)
    await source.start(["AAPL"])
    # one snapshot probe, then Friday and Thursday; the weekend costs no calls
    assert client.calls == [("snapshot", "AAPL"), ("grouped", "2026-10-02"), ("grouped", "2026-10-01")]
    assert source.status()["mode"] == "eod"
    assert (cache.get("AAPL").price, cache.get("AAPL").prev_close) == (192.0, 190.0)
    await source.add_ticker("MSFT")  # served from the stored EOD data, no extra call
    assert cache.get_price("MSFT") == 420.0
    assert len(client.calls) == 3
    await source.stop()


async def test_eod_skips_holidays_and_days_the_plan_cannot_see(monkeypatch):
    monkeypatch.setattr(massive_module, "us_market_today", lambda: date(2026, 9, 9))  # a Wednesday
    client = FakeClient(
        snapshot_error=BadResponse(NOT_AUTHORIZED),
        grouped={
            "2026-09-08": BadResponse(NOT_AUTHORIZED),  # Tuesday: not on this plan (yet)
            "2026-09-07": [],  # Monday: Labor Day, market closed
            "2026-09-04": bars(AAPL=192.0),  # Friday
            "2026-09-03": bars(AAPL=190.0),  # Thursday
        },
    )
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", client=client)
    await source.start(["AAPL"])
    assert [day for _, day in client.calls[1:]] == ["2026-09-08", "2026-09-07", "2026-09-04", "2026-09-03"]
    assert (cache.get("AAPL").price, cache.get("AAPL").prev_close) == (192.0, 190.0)
    await source.stop()


async def test_eod_with_one_session_uses_its_close_as_prev_close(monday):
    client = FakeClient(snapshot_error=BadResponse(NOT_AUTHORIZED), grouped={"2026-10-02": bars(AAPL=192.0)})
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", client=client)
    await source.start(["AAPL"])
    assert (cache.get("AAPL").price, cache.get("AAPL").prev_close) == (192.0, 192.0)
    assert source.status()["last_error"] is None
    await source.stop()


async def test_eod_lookups_are_capped(monday):
    client = FakeClient(snapshot_error=BadResponse(NOT_AUTHORIZED))  # no grouped data at all
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", client=client)
    await source.start(["AAPL"])
    assert len(client.calls) == 1 + MAX_EOD_LOOKUPS  # stays within the free plan's 5 calls/min
    assert "no grouped daily bars" in source.status()["last_error"]
    assert cache.get("AAPL") is None
    await source.stop()


async def test_failures_back_off_and_recover():
    client = FakeClient(snapshot_error=BadResponse('{"status":"ERROR","error":"Unknown API Key"}'))
    source = MassiveDataSource(PriceCache(), "bad-key", poll_seconds=15, client=client)
    await source.start(["AAPL"])
    assert "Unknown API Key" in source.status()["last_error"]
    assert source.status()["mode"] == "snapshot"  # a bad key is not mistaken for the free plan
    assert source._next_delay() == 30
    await source._refresh()
    assert source._next_delay() == 60
    client.snapshot_error, client.snapshots = None, {"AAPL": snap("AAPL", minute=191.5)}
    await source._refresh()
    assert source._next_delay() == 15
    assert source.status()["last_error"] is None
    await source.stop()


async def test_downgrade_while_running_switches_to_eod(monday):
    client = FakeClient([snap("AAPL", minute=191.5)], grouped={"2026-10-02": bars(AAPL=192.0)})
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", poll_seconds=2, client=client)  # fast polling on a paid plan
    await source.start(["AAPL"])
    client.snapshot_error = BadResponse(NOT_AUTHORIZED)  # the plan is downgraded
    await source._refresh()  # the next background poll
    assert source.status()["mode"] == "eod"
    assert cache.get_price("AAPL") == 192.0
    await source.stop()


async def test_free_plan_retries_at_most_once_a_minute(monday):
    client = FakeClient(snapshot_error=BadResponse(NOT_AUTHORIZED))  # no EOD data either: refreshes fail
    source = MassiveDataSource(PriceCache(), "key", poll_seconds=2, client=client)  # left over from a paid plan
    await source.start(["AAPL"])
    assert source._next_delay() == 60  # not 4s: the free plan allows 5 calls a minute
    await source.stop()


@pytest.mark.parametrize("error", [MaxRetryError(None, "/v2/snapshot", "refused"), KeyError("surprise")])
async def test_polling_survives_errors(error):
    client = FakeClient(snapshot_error=error)
    source = MassiveDataSource(PriceCache(), "key", poll_seconds=0.001, client=client)
    await source.start(["AAPL"])
    await asyncio.sleep(0.05)
    assert len(client.calls) >= 3  # the background loop kept polling after the first failure
    await source.stop()
```

**`backend/tests/routes/test_stream.py`**

```python
import asyncio
import json
import socket

import httpx
import uvicorn
from fastapi import FastAPI

from app.routes import stream
from app.services.market import PriceCache


async def test_stream_sends_full_state_then_every_change():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    app = FastAPI()
    app.state.price_cache = cache
    app.include_router(stream.router)

    with socket.socket() as s:  # find a free port
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            async with client.stream("GET", f"http://127.0.0.1:{port}/api/stream/prices") as resp:
                assert resp.headers["content-type"].startswith("text/event-stream")
                assert resp.headers["cache-control"] == "no-cache"
                lines = resp.aiter_lines()

                async def next_event() -> dict[str, str]:
                    """Read up to the blank line that ends an event; return its fields."""
                    event: dict[str, str] = {}
                    async for line in lines:
                        if line:
                            field, _, value = line.partition(": ")
                            event[field] = value
                        elif "data" in event:
                            return event

                first = await next_event()
                assert first["retry"] == "1000"  # reconnect hint, sent once
                prices = json.loads(first["data"])
                assert (prices["AAPL"]["price"], prices["AAPL"]["direction"]) == (190.0, "flat")

                cache.update("AAPL", 190.5)
                prices = json.loads((await next_event())["data"])
                assert (prices["AAPL"]["previous_price"], prices["AAPL"]["direction"]) == (190.0, "up")

                cache.remove("AAPL")
                cache.update("MSFT", 420.0)
                third = await next_event()
                assert list(json.loads(third["data"])) == ["MSFT"]  # removed tickers drop out
                assert "retry" not in third
    finally:
        server.should_exit = True
        await serving
```
