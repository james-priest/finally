import asyncio
from contextlib import suppress

import pytest

import db
from app.services import portfolio
from app.services.market import PriceCache
from app.services.portfolio import TradeError
from tests.services.fakes import FakeSource


@pytest.fixture
async def market():
    db.init_db()
    cache = PriceCache()
    source = FakeSource(cache, {"AAPL": 190.0, "PYPL": 60.0})
    await source.start(db.tracked_tickers())
    return source, cache


async def test_buy_records_trade_position_cash_and_snapshot(market):
    source, cache = market
    trade = await portfolio.execute_trade("AAPL", "buy", 10, source, cache)
    assert trade["ticker"] == "AAPL" and trade["side"] == "buy" and trade["price"] == 190.0
    assert db.get_cash() == 8_100.0
    assert db.get_position("AAPL")["avg_cost"] == 190.0
    assert [s["total_value"] for s in portfolio.get_history()] == [10_000.0]


async def test_buy_of_unwatched_ticker_starts_tracking_it(market):
    source, cache = market
    await portfolio.execute_trade(" pypl ", "buy", 1, source, cache)  # the chat flow passes raw symbols
    assert "PYPL" in source.get_tickers()
    assert db.get_position("PYPL")["quantity"] == 1


async def test_full_sell_deletes_the_position_and_stops_tracking_an_unwatched_ticker(market):
    source, cache = market
    await portfolio.execute_trade("PYPL", "buy", 2, source, cache)
    await portfolio.execute_trade("PYPL", "sell", 2, source, cache)
    assert db.get_position("PYPL") is None
    assert "PYPL" not in source.get_tickers()
    assert db.get_cash() == 10_000.0


async def test_failed_trade_changes_nothing_and_untracks_the_ticker(market):
    source, cache = market
    with pytest.raises(TradeError, match="Insufficient shares"):
        await portfolio.execute_trade("PYPL", "sell", 1, source, cache)
    with pytest.raises(TradeError, match="Insufficient cash"):
        await portfolio.execute_trade("AAPL", "buy", 1_000, source, cache)
    assert db.get_cash() == 10_000.0
    assert db.get_positions() == []
    assert portfolio.get_history() == []
    assert "PYPL" not in source.get_tickers()


@pytest.mark.parametrize(
    ("ticker", "side", "quantity", "message"),
    [
        ("NOPRICE", "buy", 1, "No price available"),
        ("bad ticker!", "buy", 1, "Invalid ticker"),
        ("AAPL", "hold", 1, "Side must be"),
        ("AAPL", "buy", -1, "greater than zero"),
    ],
)
async def test_invalid_trades_raise_trade_error(market, ticker, side, quantity, message):
    source, cache = market
    with pytest.raises(TradeError, match=message):
        await portfolio.execute_trade(ticker, side, quantity, source, cache)


async def test_get_portfolio_values_positions_at_live_prices(market):
    source, cache = market
    await portfolio.execute_trade("AAPL", "buy", 10, source, cache)
    cache.update("AAPL", 190.5)
    result = portfolio.get_portfolio(cache)
    assert result["total_value"] == 10_005.0
    assert result["positions"][0]["unrealized_pnl_percent"] == 0.2632


async def test_snapshot_loop_records_at_once_and_survives_errors(market, monkeypatch):
    _, cache = market
    calls = 0
    real = db.insert_snapshot
    recovered = asyncio.Event()

    def flaky(total_value):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("disk full")
        recovered.set()
        return real(total_value)

    monkeypatch.setattr(db, "insert_snapshot", flaky)
    task = asyncio.create_task(portfolio.run_snapshots(cache, interval=0.01))
    try:
        async with asyncio.timeout(2):
            await recovered.wait()
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert calls >= 2
    assert portfolio.get_history()[0]["total_value"] == 10_000.0


async def test_concurrent_buys_cannot_overspend(market):
    source, cache = market
    buys = (portfolio.execute_trade("AAPL", "buy", 30, source, cache) for _ in range(2))  # $5,700 each
    results = await asyncio.gather(*buys, return_exceptions=True)
    assert sum(isinstance(r, TradeError) for r in results) == 1
    assert db.get_cash() == 10_000.0 - 30 * 190.0
    assert db.get_position("AAPL")["quantity"] == 30


async def test_concurrent_buys_both_land(market):
    source, cache = market
    await asyncio.gather(*(portfolio.execute_trade("AAPL", "buy", 5, source, cache) for _ in range(2)))
    assert db.get_cash() == 10_000.0 - 10 * 190.0
    assert db.get_position("AAPL")["quantity"] == 10
