import pytest


async def test_fresh_portfolio_is_all_cash(client):
    resp = await client.get("/api/portfolio")
    assert resp.status_code == 200
    assert resp.json() == {
        "cash_balance": 10_000.0,
        "positions_value": 0.0,
        "total_value": 10_000.0,
        "unrealized_pnl": 0.0,
        "positions": [],
    }


async def test_buy_then_sell_round_trip(client):
    resp = await client.post("/api/portfolio/trade", json={"ticker": "aapl", "quantity": 10, "side": "buy"})
    assert resp.status_code == 200
    body = resp.json()
    trade = body["trade"]
    assert set(trade) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert trade["ticker"] == "AAPL" and trade["quantity"] == 10.0
    assert body["portfolio"]["cash_balance"] == pytest.approx(10_000 - 10 * trade["price"], abs=0.01)
    [position] = body["portfolio"]["positions"]
    assert position["ticker"] == "AAPL" and position["avg_cost"] == trade["price"]

    resp = await client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10, "side": "sell"})
    assert resp.status_code == 200
    assert resp.json()["portfolio"]["positions"] == []

    snapshots = (await client.get("/api/portfolio/history")).json()["snapshots"]
    assert len(snapshots) >= 3  # startup + one per trade
    assert set(snapshots[0]) == {"total_value", "recorded_at"}


@pytest.mark.parametrize(
    "body",
    [
        {"ticker": "AAPL", "quantity": 0, "side": "buy"},
        {"ticker": "AAPL", "quantity": -1, "side": "buy"},
        {"ticker": "AAPL", "quantity": 1, "side": "hold"},
        {"ticker": "not a ticker", "quantity": 1, "side": "buy"},
        {"ticker": "AAPL", "side": "buy"},
    ],
)
async def test_invalid_trade_input_is_422(client, body):
    resp = await client.post("/api/portfolio/trade", json=body)
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"ticker": "AAPL", "quantity": 1_000_000, "side": "buy"}, "Insufficient cash"),
        ({"ticker": "AAPL", "quantity": 1, "side": "sell"}, "Insufficient shares"),
    ],
)
async def test_failed_validation_is_400(client, body, message):
    resp = await client.post("/api/portfolio/trade", json=body)
    assert resp.status_code == 400
    assert message in resp.json()["detail"]


async def test_history_includes_the_startup_snapshot(client):
    resp = await client.get("/api/portfolio/history")
    assert resp.status_code == 200
    assert resp.json()["snapshots"][0]["total_value"] == 10_000.0
