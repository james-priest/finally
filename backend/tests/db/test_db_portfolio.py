import sqlite3

import pytest

import db


@pytest.fixture(autouse=True)
def seeded(temp_db):
    db.init_db()


def trade_rows(path) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT ticker, side, quantity, price FROM trades ORDER BY rowid").fetchall()


def test_cash_get_and_set():
    assert db.get_cash() == 10000.0
    db.set_cash(9500.5)
    assert db.get_cash() == 9500.5


def test_positions_upsert_get_list_delete():
    assert db.get_positions() == []
    assert db.get_position("MSFT") is None
    db.upsert_position("MSFT", 2, 400.0)
    db.upsert_position("AAPL", 1.5, 190.0)
    db.upsert_position("MSFT", 3, 410.0)
    assert [(p["ticker"], p["quantity"], p["avg_cost"]) for p in db.get_positions()] == [
        ("AAPL", 1.5, 190.0),
        ("MSFT", 3.0, 410.0),
    ]
    assert db.get_position("MSFT")["quantity"] == 3.0
    db.delete_position("MSFT")
    assert db.get_position("MSFT") is None


def test_insert_trade_returns_contract_shape(temp_db):
    trade = db.insert_trade("AAPL", "buy", 10, 190)
    assert set(trade) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert trade["quantity"] == 10.0 and isinstance(trade["quantity"], float)
    assert trade_rows(temp_db) == [("AAPL", "buy", 10.0, 190.0)]


def test_record_trade_buy_writes_cash_position_and_trade(temp_db):
    trade = db.record_trade("AAPL", "buy", 10, 190.0, cash=8100.0, position=(10, 190.0))
    assert trade["ticker"] == "AAPL" and trade["side"] == "buy"
    assert db.get_cash() == 8100.0
    assert db.get_position("AAPL")["avg_cost"] == 190.0
    assert trade_rows(temp_db) == [("AAPL", "buy", 10.0, 190.0)]


def test_record_trade_with_no_position_deletes_the_row(temp_db):
    db.record_trade("AAPL", "buy", 10, 190.0, cash=8100.0, position=(10, 190.0))
    db.record_trade("AAPL", "sell", 10, 200.0, cash=10100.0, position=None)
    assert db.get_position("AAPL") is None
    assert db.get_cash() == 10100.0
    assert len(trade_rows(temp_db)) == 2


def test_record_trade_is_atomic(temp_db, monkeypatch):
    """A failure partway through leaves cash, positions and trades untouched."""

    def boom(*args):
        raise sqlite3.OperationalError("disk on fire")

    monkeypatch.setattr(db.portfolio, "_upsert_position", boom)
    with pytest.raises(sqlite3.OperationalError):
        db.record_trade("AAPL", "buy", 10, 190.0, cash=8100.0, position=(10, 190.0))
    assert db.get_cash() == 10000.0
    assert db.get_positions() == []
    assert trade_rows(temp_db) == []
