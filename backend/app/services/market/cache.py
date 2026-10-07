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
