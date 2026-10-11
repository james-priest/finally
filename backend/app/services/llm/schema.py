"""The structured output the LLM must return (PLAN.md §9)."""

from typing import Literal

from pydantic import BaseModel


class TradeInstruction(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    quantity: float


class WatchlistInstruction(BaseModel):
    ticker: str
    action: Literal["add", "remove"]


class LLMReply(BaseModel):
    """Validation of tickers and quantities happens at execution, through the same services as the REST routes."""

    message: str
    trades: list[TradeInstruction] = []
    watchlist_changes: list[WatchlistInstruction] = []
