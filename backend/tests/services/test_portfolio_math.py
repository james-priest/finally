import pytest

from app.services.market import PriceCache
from app.services.portfolio import Holding, TradeError, apply_trade, value_portfolio


def test_buy_opens_a_position_and_spends_cash():
    cash, holding = apply_trade("buy", 10, 190.0, 10_000.0, None)
    assert cash == pytest.approx(8_100.0)
    assert holding == Holding(10, 190.0)


def test_buy_averages_the_cost_of_an_existing_position():
    _, holding = apply_trade("buy", 10, 200.0, 10_000.0, Holding(10, 100.0))
    assert holding == Holding(20, 150.0)


def test_buy_with_insufficient_cash_fails():
    with pytest.raises(TradeError, match="Insufficient cash"):
        apply_trade("buy", 100, 190.0, 10_000.0, None)


def test_buy_spending_exactly_all_cash_succeeds():
    cash, _ = apply_trade("buy", 0.1, 100.0, 10.0, None)
    assert cash == pytest.approx(0.0)


def test_partial_sell_keeps_avg_cost():
    cash, holding = apply_trade("sell", 4, 210.0, 0.0, Holding(10, 190.0))
    assert cash == pytest.approx(840.0)
    assert holding == Holding(6, 190.0)


def test_selling_at_a_loss_returns_proceeds():
    cash, holding = apply_trade("sell", 10, 150.0, 0.0, Holding(10, 190.0))
    assert cash == pytest.approx(1_500.0)
    assert holding is None  # full sell closes the position


def test_full_sell_of_fractional_shares_closes_the_position():
    _, holding = apply_trade("sell", 0.3, 100.0, 0.0, Holding(0.1 + 0.2, 100.0))  # 0.30000000000000004
    assert holding is None


@pytest.mark.parametrize("holding", [None, Holding(5, 100.0)])
def test_selling_more_than_owned_fails(holding):
    with pytest.raises(TradeError, match="Insufficient shares"):
        apply_trade("sell", 6, 100.0, 0.0, holding)


def test_non_positive_quantity_fails():
    with pytest.raises(TradeError, match="greater than zero"):
        apply_trade("buy", 0, 100.0, 1_000.0, None)


def test_value_portfolio_matches_the_contract_example():
    cache = PriceCache()
    cache.update("AAPL", 190.5)
    result = value_portfolio(8_100.0, {"AAPL": Holding(10, 190.0)}, cache)
    assert result == {
        "cash_balance": 8_100.0,
        "positions_value": 1_905.0,
        "total_value": 10_005.0,
        "unrealized_pnl": 5.0,
        "positions": [
            {
                "ticker": "AAPL",
                "quantity": 10,
                "avg_cost": 190.0,
                "current_price": 190.5,
                "market_value": 1_905.0,
                "unrealized_pnl": 5.0,
                "unrealized_pnl_percent": 0.2632,
            }
        ],
    }


def test_value_portfolio_uses_avg_cost_without_a_price_and_sorts_by_ticker():
    cache = PriceCache()
    cache.update("AAPL", 200.0)
    result = value_portfolio(0.0, {"ZZZ": Holding(2, 50.0), "AAPL": Holding(1, 100.0)}, cache)
    assert [p["ticker"] for p in result["positions"]] == ["AAPL", "ZZZ"]
    zzz = result["positions"][1]
    assert zzz["current_price"] == 50.0
    assert zzz["unrealized_pnl"] == 0.0
    assert result["total_value"] == 300.0
    assert result["unrealized_pnl"] == 100.0


def test_value_portfolio_with_no_positions():
    result = value_portfolio(10_000.0, {}, PriceCache())
    assert result["total_value"] == 10_000.0
    assert result["positions"] == []
