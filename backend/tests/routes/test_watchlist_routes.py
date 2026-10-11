from app.main import app

DEFAULTS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


async def test_get_watchlist_returns_defaults_with_quotes(client):
    resp = await client.get("/api/watchlist")
    assert resp.status_code == 200
    tickers = resp.json()["tickers"]
    assert [t["ticker"] for t in tickers] == DEFAULTS
    assert set(tickers[0]) == {"ticker", "added_at", "quote"}
    assert tickers[0]["quote"]["ticker"] == "AAPL"
    assert tickers[0]["quote"]["price"] > 0


async def test_add_then_remove(client):
    resp = await client.post("/api/watchlist", json={"ticker": "pypl"})
    assert resp.status_code == 201
    entry = resp.json()
    assert entry["ticker"] == "PYPL" and entry["quote"]["price"] > 0
    assert "PYPL" in app.state.market_source.get_tickers()
    resp = await client.delete("/api/watchlist/PYPL")
    assert resp.status_code == 204
    tickers = [t["ticker"] for t in (await client.get("/api/watchlist")).json()["tickers"]]
    assert "PYPL" not in tickers
    assert "PYPL" not in app.state.market_source.get_tickers()


async def test_add_duplicate_is_409(client):
    resp = await client.post("/api/watchlist", json={"ticker": "AAPL"})
    assert resp.status_code == 409
    assert "already" in resp.json()["detail"]


async def test_add_invalid_is_422(client):
    resp = await client.post("/api/watchlist", json={"ticker": "not a ticker"})
    assert resp.status_code == 422


async def test_remove_missing_is_404(client):
    resp = await client.delete("/api/watchlist/PYPL")
    assert resp.status_code == 404
