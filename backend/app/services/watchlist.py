"""Watchlist changes and listing. Shared by the REST routes and the chat flow."""

import db
from app.services.market import MarketDataSource, PriceCache, normalize_ticker


class WatchlistError(Exception):
    """A watchlist change failed: invalid ticker, already present (add) or not present (remove)."""


def _entry(item: dict, cache: PriceCache) -> dict:
    quote = cache.get(item["ticker"])
    return {"ticker": item["ticker"], "added_at": item["added_at"], "quote": quote.to_dict() if quote else None}


def _normalize(ticker: str) -> str:
    try:
        return normalize_ticker(ticker)
    except ValueError as e:
        raise WatchlistError(str(e)) from e


def list_watchlist(cache: PriceCache) -> list[dict]:
    """Entries in insertion order: {ticker, added_at, quote}, where quote is a PriceUpdate dict or None."""
    return [_entry(item, cache) for item in db.list_watchlist()]


async def add_ticker(ticker: str, source: MarketDataSource, cache: PriceCache) -> dict:
    """Add a ticker, start pricing it, and return its entry. Raises WatchlistError if already present."""
    ticker = _normalize(ticker)
    item = db.add_to_watchlist(ticker)
    if item is None:
        raise WatchlistError(f"{ticker} is already on the watchlist")
    await source.sync_tickers(db.tracked_tickers())  # prices the new ticker right away
    return _entry(item, cache)


async def remove_ticker(ticker: str, source: MarketDataSource) -> None:
    """Remove a ticker. Raises WatchlistError if it is not on the watchlist."""
    ticker = _normalize(ticker)
    if not db.remove_from_watchlist(ticker):
        raise WatchlistError(f"{ticker} is not on the watchlist")
    await source.sync_tickers(db.tracked_tickers())  # keeps pricing it while a position is open
