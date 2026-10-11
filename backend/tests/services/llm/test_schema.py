import pytest
from pydantic import ValidationError

from app.services.llm import LLMReply


def test_full_reply_parses():
    reply = LLMReply.model_validate_json(
        '{"message": "Done.", "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}],'
        ' "watchlist_changes": [{"ticker": "PYPL", "action": "add"}]}'
    )
    assert reply.message == "Done."
    assert reply.trades[0].ticker == "AAPL"
    assert reply.trades[0].side == "buy"
    assert reply.trades[0].quantity == 10.0
    assert reply.watchlist_changes[0].action == "add"


def test_optional_lists_default_to_empty():
    reply = LLMReply.model_validate_json('{"message": "Hello"}')
    assert reply.trades == []
    assert reply.watchlist_changes == []


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"trades": []}',  # message is required
        '{"message": "x", "trades": [{"ticker": "AAPL", "side": "hold", "quantity": 1}]}',
        '{"message": "x", "trades": [{"ticker": "AAPL", "side": "buy", "quantity": "lots"}]}',
        '{"message": "x", "watchlist_changes": [{"ticker": "AAPL", "action": "pin"}]}',
    ],
)
def test_malformed_replies_raise(raw):
    with pytest.raises(ValidationError):
        LLMReply.model_validate_json(raw)
