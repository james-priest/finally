from collections.abc import Iterable

from app.services.market import MarketDataSource, PriceCache


class FakeSource(MarketDataSource):
    """Prices tickers from a fixed table, instantly. A ticker missing from the table gets no price."""

    def __init__(self, cache: PriceCache, prices: dict[str, float]) -> None:
        self.cache = cache
        self.prices = prices
        self.tickers: set[str] = set()

    async def start(self, tickers: Iterable[str]) -> None:
        for t in tickers:
            await self.add_ticker(t)

    async def stop(self) -> None:
        pass

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self.tickers:
            return
        self.tickers.add(ticker)
        if ticker in self.prices:
            self.cache.update(ticker, self.prices[ticker])

    async def remove_ticker(self, ticker: str) -> None:
        self.tickers.discard(ticker)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self.tickers)
