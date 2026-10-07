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
