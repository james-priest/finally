"""Portfolio snapshots and chat messages: append-only logs read back oldest first."""

import pytest

import db


@pytest.fixture(autouse=True)
def seeded(temp_db):
    db.init_db()


def test_snapshots_insert_and_list_oldest_first():
    assert db.list_snapshots() == []
    first = db.insert_snapshot(10000.0)
    db.insert_snapshot(10050.25)
    assert set(first) == {"total_value", "recorded_at"}
    assert [s["total_value"] for s in db.list_snapshots()] == [10000.0, 10050.25]


def test_chat_message_round_trip_with_json_actions():
    actions = {
        "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 5, "status": "executed"}],
        "watchlist_changes": [],
    }
    user = db.insert_chat_message("user", "buy 5 AAPL")
    reply = db.insert_chat_message("assistant", "Bought 5 AAPL.", actions)
    assert set(reply) == {"id", "role", "content", "actions", "created_at"}
    assert db.list_chat_messages() == [user, reply]
    assert db.list_chat_messages()[0]["actions"] is None
    assert db.list_chat_messages()[1]["actions"] == actions


def test_list_chat_messages_limit_returns_most_recent_oldest_first():
    for i in range(5):
        db.insert_chat_message("user", f"m{i}")
    assert [m["content"] for m in db.list_chat_messages(limit=3)] == ["m2", "m3", "m4"]
    assert len(db.list_chat_messages()) == 5
