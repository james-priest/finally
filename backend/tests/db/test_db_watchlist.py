import pytest

import db


@pytest.fixture(autouse=True)
def seeded(temp_db):
    db.init_db()


def test_list_is_in_insertion_order_with_timestamps():
    db.add_to_watchlist("PYPL")
    entries = db.list_watchlist()
    assert [e["ticker"] for e in entries] == [*db.DEFAULT_WATCHLIST, "PYPL"]
    assert all(set(e) == {"ticker", "added_at"} for e in entries)


def test_add_returns_entry_or_none_when_present():
    entry = db.add_to_watchlist("PYPL")
    assert entry is not None and entry["ticker"] == "PYPL"
    assert db.add_to_watchlist("PYPL") is None
    assert db.watchlist_tickers().count("PYPL") == 1


def test_remove_and_contains():
    assert db.in_watchlist("AAPL")
    assert db.remove_from_watchlist("AAPL") is True
    assert not db.in_watchlist("AAPL")
    assert db.remove_from_watchlist("AAPL") is False


def test_tracked_tickers_is_watchlist_union_open_positions():
    for t in db.watchlist_tickers():
        db.remove_from_watchlist(t)
    db.add_to_watchlist("MSFT")
    db.add_to_watchlist("AAPL")
    db.upsert_position("AAPL", 1, 190.0)  # in both: listed once
    db.upsert_position("PYPL", 2, 60.0)  # held but not watched: still tracked
    db.upsert_position("ZERO", 0, 10.0)  # no shares: not tracked
    assert db.tracked_tickers() == ["AAPL", "MSFT", "PYPL"]


def test_tracked_tickers_on_fresh_db_is_default_watchlist():
    assert db.tracked_tickers() == sorted(db.DEFAULT_WATCHLIST)
