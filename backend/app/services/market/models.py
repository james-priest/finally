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
