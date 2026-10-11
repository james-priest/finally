import pytest


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")


async def test_post_chat_executes_trade_and_returns_contract_shape(client):
    resp = await client.post("/api/chat", json={"message": "buy 2 AAPL"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"id", "role", "content", "actions", "created_at"}
    assert body["role"] == "assistant"
    assert body["content"] == "Mock: buying 2 AAPL."
    trade = body["actions"]["trades"][0]
    assert set(trade) == {"ticker", "side", "quantity", "status", "price", "error"}
    assert trade["status"] == "executed" and trade["price"] > 0
    assert body["actions"]["watchlist_changes"] == []

    positions = (await client.get("/api/portfolio")).json()["positions"]
    assert [(p["ticker"], p["quantity"]) for p in positions] == [("AAPL", 2.0)]


async def test_failed_trade_is_200_with_error(client):
    resp = await client.post("/api/chat", json={"message": "buy 100000 AAPL"})
    assert resp.status_code == 200
    trade = resp.json()["actions"]["trades"][0]
    assert trade["status"] == "failed"
    assert "Insufficient cash" in trade["error"]


async def test_watchlist_change_via_chat(client):
    resp = await client.post("/api/chat", json={"message": "add PYPL"})
    assert resp.json()["actions"]["watchlist_changes"][0]["status"] == "executed"
    tickers = [t["ticker"] for t in (await client.get("/api/watchlist")).json()["tickers"]]
    assert "PYPL" in tickers


async def test_get_chat_returns_history_oldest_first(client):
    assert (await client.get("/api/chat")).json() == {"messages": []}
    await client.post("/api/chat", json={"message": "hello"})

    resp = await client.get("/api/chat")
    assert resp.status_code == 200
    messages = resp.json()["messages"]
    assert [(m["role"], m["content"], m["actions"]) for m in messages] == [
        ("user", "hello", None),
        ("assistant", "Mock: I received your message.", {"trades": [], "watchlist_changes": []}),
    ]


async def test_empty_message_is_422(client):
    assert (await client.post("/api/chat", json={"message": ""})).status_code == 422
