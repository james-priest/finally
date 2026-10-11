import pytest

import db
from app.services.llm import LLMReply, TradeInstruction, handle_chat, list_chat
from app.services.llm.chat import FALLBACK_MESSAGE
from app.services.market import PriceCache
from app.services.market.simulator import SimulatorDataSource


@pytest.fixture
async def market():
    """A seeded database and a simulator source that is never started, so prices stay at their seeds (AAPL 190)."""
    db.init_db()
    cache = PriceCache()
    source = SimulatorDataSource(cache)
    await source.sync_tickers(db.tracked_tickers())
    return source, cache


@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")


def fake_llm(monkeypatch, reply=None, error=None):
    """Replace the LLM call; records the messages it was given."""
    calls: list[list[dict]] = []

    async def call_llm(messages):
        calls.append(messages)
        if error:
            raise error
        return reply

    monkeypatch.setattr("app.services.llm.chat.call_llm", call_llm)
    return calls


async def test_buy_executes_and_both_messages_are_stored(market, mock_llm):
    source, cache = market
    result = await handle_chat("buy 5 AAPL", source, cache)

    assert result["role"] == "assistant"
    assert result["content"] == "Mock: buying 5 AAPL."
    assert set(result) == {"id", "role", "content", "actions", "created_at"}
    assert result["actions"] == {
        "trades": [
            {"ticker": "AAPL", "side": "buy", "quantity": 5.0, "status": "executed", "price": 190.0, "error": None}
        ],
        "watchlist_changes": [],
    }
    assert db.get_cash() == pytest.approx(10000.0 - 5 * 190.0)
    assert db.get_position("AAPL")["quantity"] == 5.0
    messages = await list_chat()
    assert [(m["role"], m["content"], m["actions"]) for m in messages] == [
        ("user", "buy 5 AAPL", None),
        ("assistant", "Mock: buying 5 AAPL.", result["actions"]),
    ]


async def test_insufficient_cash_is_reported_not_raised(market, mock_llm):
    source, cache = market
    result = await handle_chat("buy 1000 AAPL", source, cache)

    trade = result["actions"]["trades"][0]
    assert trade["status"] == "failed"
    assert trade["price"] is None
    assert "Insufficient cash" in trade["error"]
    assert db.get_cash() == 10000.0
    assert db.get_position("AAPL") is None


async def test_selling_unowned_shares_fails(market, mock_llm):
    source, cache = market
    result = await handle_chat("sell 1 AAPL", source, cache)
    assert "Insufficient shares" in result["actions"]["trades"][0]["error"]


async def test_watchlist_add_and_duplicate(market, mock_llm):
    source, cache = market
    added = await handle_chat("add PYPL", source, cache)
    duplicate = await handle_chat("add PYPL", source, cache)

    assert added["actions"]["watchlist_changes"] == [
        {"ticker": "PYPL", "action": "add", "status": "executed", "error": None}
    ]
    assert duplicate["actions"]["watchlist_changes"] == [
        {"ticker": "PYPL", "action": "add", "status": "failed", "error": "PYPL is already on the watchlist"}
    ]
    assert "PYPL" in db.watchlist_tickers()
    assert cache.get_price("PYPL") is not None


async def test_watchlist_remove_missing_ticker_fails(market, mock_llm):
    source, cache = market
    result = await handle_chat("remove PYPL", source, cache)
    assert result["actions"]["watchlist_changes"][0]["status"] == "failed"
    assert result["actions"]["watchlist_changes"][0]["error"] == "PYPL is not on the watchlist"


async def test_invalid_ticker_from_llm_fails_that_action_only(market, monkeypatch):
    source, cache = market
    reply = LLMReply(
        message="Trading.",
        trades=[
            TradeInstruction(ticker="NOT A TICKER", side="buy", quantity=1),
            TradeInstruction(ticker="aapl", side="buy", quantity=1),
        ],
    )
    fake_llm(monkeypatch, reply=reply)
    result = await handle_chat("trade", source, cache)

    bad, good = result["actions"]["trades"]
    assert bad["status"] == "failed"
    assert bad["error"]
    assert good == {
        "ticker": "AAPL",
        "side": "buy",
        "quantity": 1.0,
        "status": "executed",
        "price": 190.0,
        "error": None,
    }


async def test_llm_failure_returns_apology_with_no_actions(market, monkeypatch):
    source, cache = market
    fake_llm(monkeypatch, error=RuntimeError("provider down"))
    result = await handle_chat("buy 5 AAPL", source, cache)

    assert result["content"] == FALLBACK_MESSAGE
    assert result["actions"] == {"trades": [], "watchlist_changes": []}
    assert db.get_cash() == 10000.0
    assert len(await list_chat()) == 2


async def test_prompt_carries_context_and_history(market, monkeypatch):
    source, cache = market
    calls = fake_llm(monkeypatch, reply=LLMReply(message="Noted."))
    await handle_chat("first", source, cache)
    await handle_chat("second", source, cache)

    _, *turns, snapshot, latest = calls[1]
    assert turns == [{"role": "user", "content": "first"}, {"role": "assistant", "content": "Noted."}]
    assert "Cash: $10,000.00" in snapshot["content"]
    assert "- AAPL: $190.00" in snapshot["content"]
    assert latest == {"role": "user", "content": "second"}
