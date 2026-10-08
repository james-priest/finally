import asyncio
import math
import time

from .models import PriceUpdate


def round_price(price: float) -> float:
    """Cents, or 4 decimals below $1 so sub-dollar stocks keep their precision."""
    return round(price, 2 if price >= 1 else 4)


def _is_valid(price: float) -> bool:
    return math.isfinite(price) and price > 0


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
        """Store a new price. The old price becomes previous_price.

        Raises ValueError for a price that is not positive and finite after rounding.
        An unusable prev_close (None, zero, negative, NaN, infinite) carries the stored one forward.
        """
        price = round_price(price)  # NaN and infinity pass through round() unchanged
        if not _is_valid(price):
            raise ValueError(f"Invalid price for {ticker}: {price!r}")
        old = self._prices.get(ticker)
        if prev_close is not None:
            prev_close = round_price(prev_close)
        if prev_close is None or not _is_valid(prev_close):
            prev_close = old.prev_close if old else price
        update = PriceUpdate(
            ticker=ticker,
            price=price,
            previous_price=old.price if old else price,
            prev_close=prev_close,
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
