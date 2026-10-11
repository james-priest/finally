import pytest

from app.services.llm import LLMReply, TradeInstruction, WatchlistInstruction
from app.services.llm.client import call_llm, mock_enabled
from app.services.llm.mock import mock_reply


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "buy 5 AAPL",
            LLMReply(message="Mock: buying 5 AAPL.", trades=[TradeInstruction(ticker="AAPL", side="buy", quantity=5)]),
        ),
        (
            "Please SELL 2.5 nvda now",
            LLMReply(
                message="Mock: selling 2.5 NVDA.", trades=[TradeInstruction(ticker="NVDA", side="sell", quantity=2.5)]
            ),
        ),
        (
            "add pypl",
            LLMReply(
                message="Mock: adding PYPL to the watchlist.",
                watchlist_changes=[WatchlistInstruction(ticker="PYPL", action="add")],
            ),
        ),
        (
            "watch BRK.B",
            LLMReply(
                message="Mock: adding BRK.B to the watchlist.",
                watchlist_changes=[WatchlistInstruction(ticker="BRK.B", action="add")],
            ),
        ),
        (
            "Remove TSLA",
            LLMReply(
                message="Mock: removing TSLA from the watchlist.",
                watchlist_changes=[WatchlistInstruction(ticker="TSLA", action="remove")],
            ),
        ),
        ("How is my portfolio doing?", LLMReply(message="Mock: I received your message.")),
    ],
)
def test_mock_rules(text, expected):
    assert mock_reply(text) == expected


def test_first_matching_rule_wins():
    reply = mock_reply("remove TSLA and buy 1 AAPL")
    assert reply.trades == [TradeInstruction(ticker="AAPL", side="buy", quantity=1)]
    assert reply.watchlist_changes == []


@pytest.mark.parametrize(("value", "enabled"), [("true", True), ("TRUE", True), ("false", False), ("", False)])
def test_mock_enabled_reads_env(monkeypatch, value, enabled):
    monkeypatch.setenv("LLM_MOCK", value)
    assert mock_enabled() is enabled


async def test_call_llm_uses_mock_without_network(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")

    async def no_network(**kwargs):
        raise AssertionError("LiteLLM must not be called in mock mode")

    monkeypatch.setattr("app.services.llm.client.acompletion", no_network)
    reply = await call_llm([{"role": "system", "content": "..."}, {"role": "user", "content": "buy 3 MSFT"}])
    assert reply.trades == [TradeInstruction(ticker="MSFT", side="buy", quantity=3)]
