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
