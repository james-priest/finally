# Market Simulator

> **Superseded:** implement from [MARKET_DATA_DESIGN.md](MARKET_DATA_DESIGN.md) §9. The code below is an earlier draft; the model and its derivations still apply.

How FinAlly makes up realistic-looking live prices when no `MASSIVE_API_KEY` is set. This is the default mode. The simulator implements `MarketDataSource` from [MARKET_INTERFACE.md](MARKET_INTERFACE.md) and writes into the same `PriceCache` the Massive source uses, so nothing downstream can tell which one is running.

## 1. Goals

- Prices that **move visibly** every 500ms, so green and red flashes and sparklines fill in quickly.
- Movements that **look like a real market**: lognormal prices, a volatility per ticker, tech stocks moving together, and the odd sharp jump.
- **No dependencies.** Python stdlib only (`random`, `math`), running as an in-process asyncio task.
- **Deterministic when seeded**, for tests.
- **Any ticker works.** Tickers added to the watchlist get believable parameters automatically.

## 2. Model

### 2.1 Geometric Brownian Motion

Each tick moves every ticker by the exact GBM step:

```
S(t+dt) = S(t) · exp( (μ − σ²/2)·dt + σ·√dt·Z )
```

- `μ` is the annual drift and `σ` the annual volatility (per-ticker profile).
- `Z ~ N(0,1)` is a **correlated** shock (§2.2).
- Working in log-space keeps prices positive and makes returns lognormal.

### 2.2 Correlated moves: a factor model

Each tick draws one market shock, one shock per sector, and one shock per ticker, and blends them:

```
Z_i = √w_m · M  +  √w_s · S_sector(i)  +  √(1 − w_m − w_s) · ε_i
```

`M`, `S_k` and `ε_i` are independent `N(0,1)` draws. The weights add up to 1, so `Z_i` still has unit variance. The correlations that come out are:

| Pair             | Correlation      | Default (`w_m = 0.3`, `w_s = 0.3`) | Measured (20k ticks) |
| ---------------- | ---------------- | ---------------------------------- | -------------------- |
| Same sector      | `w_m + w_s`      | 0.60                               | AAPL–MSFT 0.60, NVDA–META 0.60, JPM–V 0.60 |
| Different sector | `w_m`            | 0.30                               | AAPL–JPM 0.30, TSLA–NFLX 0.31 |

This is simpler than a Cholesky-decomposed correlation matrix. Adding or removing a ticker at runtime needs no matrix rebuild, and the cost is O(n) per tick.

### 2.3 Random events

Each tick, each ticker has a chance `p = 0.0005` of a jump of ±2–5% (uniform size, random sign), added to the log return. With 10 tickers at 2 ticks/s that is **about one event every 100 seconds** across the watchlist (measured: 95 events in 167 minutes). That is often enough to be noticed without being chaotic.

### 2.4 Time scale: why prices move faster than real time

At real-world volatility, a 500ms step is tiny. With `σ = 0.25` per year and 252 × 6.5h trading years:

```
σ_tick = 0.25 · √(0.5 / 5,896,800) ≈ 0.0073%  →  about $0.014 per tick on a $190 stock
```

After rounding to cents, most ticks would show no change. So the simulator runs a **compressed clock**: each tick advances `time_scale` (default **20**) trading-seconds' worth of volatility.

```
dt = tick_seconds · time_scale / TRADING_SECONDS_PER_YEAR = 0.5 · 20 / 5,896,800 ≈ 1.7e-6 years
```

Measured at the defaults (20,000 ticks, events off):

| Ticker | σ (annual) | Per tick        | 1 min  | 10 min | 1 hour |
| ------ | ---------- | --------------- | ------ | ------ | ------ |
| V      | 0.20       | 0.026% (~$0.07) | 0.29%  | 0.90%  | 2.2%   |
| AAPL   | 0.25       | 0.033% (~$0.06) | 0.36%  | 1.13%  | 2.8%   |
| NVDA   | 0.50       | 0.065% (~$0.09) | 0.72%  | 2.26%  | 5.5%   |
| TSLA   | 0.60       | 0.078% (~$0.20) | 0.86%  | 2.71%  | 6.7%   |

(Figures are one standard deviation.) AAPL's displayed price stays the same on only about 7% of ticks. Raise `time_scale` for a busier demo or lower it for a calmer one. Volatility grows with `√time_scale`.

## 3. Ticker Profiles

Seed prices are rough and for illustration only, not current quotes. AAPL and GOOGL match the examples in PLAN.md.

| Ticker | Seed   | σ    | μ    | Sector  |
| ------ | ------ | ---- | ---- | ------- |
| AAPL   | 190    | 0.25 | 0.08 | tech    |
| GOOGL  | 175    | 0.30 | 0.08 | tech    |
| MSFT   | 420    | 0.25 | 0.08 | tech    |
| AMZN   | 185    | 0.32 | 0.08 | tech    |
| NVDA   | 130    | 0.50 | 0.12 | tech    |
| META   | 500    | 0.40 | 0.08 | tech    |
| TSLA   | 250    | 0.60 | 0.05 | auto    |
| NFLX   | 650    | 0.40 | 0.08 | media   |
| JPM    | 200    | 0.22 | 0.06 | finance |
| V      | 280    | 0.20 | 0.06 | finance |

**Any other ticker** (e.g. PYPL added through chat) gets σ = 0.30 and μ = 0.08. Its seed price comes from the ticker name, `50 + crc32(ticker) % 25000 / 100`, which gives **$50–$300**. The same ticker always starts at the same price, across restarts too, and tests can rely on it. Unlike Python's `hash()`, `crc32` is not randomized per process. Each unknown ticker is its own sector, so it moves with the market (0.30) but has no sector peers.

## 4. Code — `services/market/simulator.py`

Two classes:

- `GBMSimulator` does the math only: no asyncio, no I/O, easy to test.
- `SimulatorDataSource` is the async wrapper that implements `MarketDataSource` and writes each tick into the cache.

```python
import asyncio
import math
import random
import zlib
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass

from .base import MarketDataSource
from .cache import PriceCache

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
    """Known profile, or a deterministic default ($50-$300) for any other ticker."""
    if ticker in PROFILES:
        return PROFILES[ticker]
    seed_price = 50.0 + zlib.crc32(ticker.encode()) % 25000 / 100
    return TickerProfile(seed_price, 0.30, 0.08, sector=ticker)


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
        self.dt = tick_seconds * time_scale / TRADING_SECONDS_PER_YEAR
        self._market_w = math.sqrt(market_weight)
        self._sector_w = math.sqrt(sector_weight)
        self._own_w = math.sqrt(1.0 - market_weight - sector_weight)
        self._event_probability = event_probability
        self._rng = rng or random.Random()
        self._prices: dict[str, float] = {}

    def add(self, ticker: str) -> float:
        """Start simulating a ticker; returns its current price."""
        if ticker not in self._prices:
            self._prices[ticker] = profile_for(ticker).seed_price
        return self._prices[ticker]

    def remove(self, ticker: str) -> None:
        self._prices.pop(ticker, None)

    def tickers(self) -> list[str]:
        return list(self._prices)

    def step(self) -> dict[str, float]:
        """Advance every ticker by one tick and return the new prices."""
        rng = self._rng
        market = rng.gauss(0.0, 1.0)
        sectors: dict[str, float] = {}
        for ticker, price in self._prices.items():
            p = profile_for(ticker)
            if p.sector not in sectors:
                sectors[p.sector] = rng.gauss(0.0, 1.0)
            z = (
                self._market_w * market
                + self._sector_w * sectors[p.sector]
                + self._own_w * rng.gauss(0.0, 1.0)
            )
            log_return = (p.drift - 0.5 * p.volatility**2) * self.dt + p.volatility * math.sqrt(self.dt) * z
            if rng.random() < self._event_probability:
                log_return += math.log1p(rng.choice((-1, 1)) * rng.uniform(0.02, 0.05))
            self._prices[ticker] = price * math.exp(log_return)
        return dict(self._prices)


class SimulatorDataSource(MarketDataSource):
    """Runs GBMSimulator in a background task, writing each tick into the cache."""

    def __init__(self, cache: PriceCache, tick_seconds: float = 0.5, simulator: GBMSimulator | None = None) -> None:
        self._cache = cache
        self._tick_seconds = tick_seconds
        self._sim = simulator or GBMSimulator(tick_seconds=tick_seconds)
        self._task: asyncio.Task | None = None

    async def start(self, tickers: Iterable[str]) -> None:
        for ticker in tickers:
            self.add_ticker(ticker)
        self._task = asyncio.create_task(self._run(), name="market-simulator")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    def add_ticker(self, ticker: str) -> None:
        if self._cache.get(ticker) is None:
            self._cache.update(ticker, self._sim.add(ticker))

    def remove_ticker(self, ticker: str) -> None:
        self._sim.remove(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.tickers()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._tick_seconds)
            for ticker, price in self._sim.step().items():
                self._cache.update(ticker, price)
```

Implementation notes:

- The simulator keeps **unrounded** prices internally. `PriceCache.update` rounds to cents for display. Rounding inside the simulator would bias small moves.
- `add_ticker` writes the seed price into the cache **straight away**, so a newly added ticker can be traded before the next tick.
- The first cache write for a ticker sets `prev_close` to the seed price. After that `prev_close` is carried forward, so `day_change_percent` is the change since the session started (since the server started).
- The whole step runs synchronously, with no `await` between ticker updates. An SSE reader therefore never sees half a tick.

## 5. Tuning Knobs

All are `GBMSimulator` constructor arguments. No env vars, to keep configuration small. Add one only if a real need comes up.

| Parameter           | Default  | Effect                                                  |
| ------------------- | -------- | ------------------------------------------------------- |
| `tick_seconds`      | 0.5      | Real time between ticks (matches the SSE cadence)       |
| `time_scale`        | 20       | Trading-seconds of volatility per real second           |
| `market_weight`     | 0.3      | Share of variance from the market factor                |
| `sector_weight`     | 0.3      | Share of variance from the sector factor                |
| `event_probability` | 0.0005   | Jump chance per ticker per tick                         |
| `rng`               | unseeded | Pass `random.Random(seed)` for reproducible runs        |

## 6. Testing

- **Determinism:** two simulators seeded the same way produce identical paths (see `test_simulator_is_deterministic_with_seed` in MARKET_INTERFACE.md §9).
- **Source behavior:** seeding on `start`, ticks written to the cache, `add_ticker` and `remove_ticker` (`test_simulator_source_writes_ticks`).
- **Statistics (optional, slower):** run about 20k steps with `event_probability=0` and a fixed seed, then check that the per-tick log-return standard deviation is close to `σ·√dt` and the correlations are close to the values in §2.2. These are the checks behind the numbers in this document.

## 7. Known Limitations

| Limitation                                    | Impact / Mitigation                                                                  |
| --------------------------------------------- | ------------------------------------------------------------------------------------ |
| Prices reset to seed values on restart        | Existing positions may show a sudden P&L jump after a restart. If that matters later, seed from the last trade price in the DB. |
| No market hours: prices move 24/7             | Intended for a demo.                                                                 |
| No mean reversion                             | Over many hours prices wander far from their seeds (AAPL 1h σ ≈ 2.8%). Fine for a demo session. |
| Seed prices are illustrative                  | Update `PROFILES` if realism vs. current quotes matters.                             |
