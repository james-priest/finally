import pytest

import db
from app.services import portfolio, watchlist
from app.services.market import PriceCache
from app.services.watchlist import WatchlistError
from tests.services.fakes import FakeSource


@pytest.fixture
async def market():
    db.init_db()
    cache = PriceCache()
    source = FakeSource(cache, {"AAPL": 190.0, "PYPL": 60.0})
    await source.start(db.tracked_tickers())
    return source, cache


async def test_list_returns_defaults_in_order_with_quotes(market):
    _, cache = market
    entries = watchlist.list_watchlist(cache)
    assert [e["ticker"] for e in entries] == db.DEFAULT_WATCHLIST
    assert entries[0]["quote"]["price"] == 190.0
    assert entries[1]["quote"] is None  # GOOGL has no price in the fake


async def test_add_prices_the_ticker_and_appends_it(market):
    source, cache = market
    entry = await watchlist.add_ticker("pypl", source, cache)
    assert entry["ticker"] == "PYPL"
    assert entry["quote"]["price"] == 60.0
    assert "PYPL" in source.get_tickers()
    assert watchlist.list_watchlist(cache)[-1]["ticker"] == "PYPL"


async def test_add_duplicate_fails(market):
    source, cache = market
    with pytest.raises(WatchlistError, match="already on the watchlist"):
        await watchlist.add_ticker("AAPL", source, cache)


async def test_add_invalid_ticker_fails(market):
    source, cache = market
    with pytest.raises(WatchlistError, match="Invalid ticker"):
        await watchlist.add_ticker("not a ticker", source, cache)


async def test_remove_stops_tracking(market):
    source, cache = market
    await watchlist.remove_ticker("NFLX", source)
    assert "NFLX" not in source.get_tickers()
    assert "NFLX" not in [e["ticker"] for e in watchlist.list_watchlist(cache)]


async def test_remove_keeps_tracking_a_held_ticker(market):
    source, cache = market
    await portfolio.execute_trade("AAPL", "buy", 1, source, cache)
    await watchlist.remove_ticker("AAPL", source)
    assert "AAPL" in source.get_tickers()


async def test_remove_missing_fails(market):
    source, _ = market
    with pytest.raises(WatchlistError, match="not on the watchlist"):
        await watchlist.remove_ticker("PYPL", source)
