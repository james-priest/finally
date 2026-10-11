"""Deterministic replies for LLM_MOCK=true (TEAM_CONTRACT.md §5). Replaces only the LLM call."""

import re

from app.services.llm.schema import LLMReply, TradeInstruction, WatchlistInstruction

_TICKER = r"([a-z][a-z0-9.\-]*)"
_TRADE = re.compile(rf"\b(buy|sell)\s+(\d+(?:\.\d+)?)\s+{_TICKER}", re.IGNORECASE)
_ADD = re.compile(rf"\b(?:add|watch)\s+{_TICKER}", re.IGNORECASE)
_REMOVE = re.compile(rf"\bremove\s+{_TICKER}", re.IGNORECASE)


def mock_reply(user_message: str) -> LLMReply:
    """First matching rule wins: buy, sell, add/watch, remove, then a plain acknowledgement."""
    if m := _TRADE.search(user_message):
        is_buy, qty, ticker = m.group(1).lower() == "buy", m.group(2), m.group(3).upper()
        trade = TradeInstruction(ticker=ticker, side="buy" if is_buy else "sell", quantity=float(qty))
        return LLMReply(message=f"Mock: {'buying' if is_buy else 'selling'} {qty} {ticker}.", trades=[trade])
    if m := _ADD.search(user_message):
        ticker = m.group(1).upper()
        change = WatchlistInstruction(ticker=ticker, action="add")
        return LLMReply(message=f"Mock: adding {ticker} to the watchlist.", watchlist_changes=[change])
    if m := _REMOVE.search(user_message):
        ticker = m.group(1).upper()
        change = WatchlistInstruction(ticker=ticker, action="remove")
        return LLMReply(message=f"Mock: removing {ticker} from the watchlist.", watchlist_changes=[change])
    return LLMReply(message="Mock: I received your message.")
