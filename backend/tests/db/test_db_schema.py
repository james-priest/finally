import sqlite3

import pytest

import db
from db.connection import DEFAULT_DB_PATH, db_path

TABLES = {"users_profile", "watchlist", "positions", "trades", "portfolio_snapshots", "chat_messages"}


def table_names(path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_db_path_comes_from_env_with_repo_root_default(temp_db, monkeypatch):
    assert db_path() == temp_db
    monkeypatch.delenv("DB_PATH")
    assert db_path() == DEFAULT_DB_PATH
    assert DEFAULT_DB_PATH.parent.name == "db"
    assert DEFAULT_DB_PATH.parent.parent.joinpath("backend").is_dir()


def test_init_creates_parent_dir_tables_and_seed(tmp_path, monkeypatch):
    path = tmp_path / "missing" / "dir" / "finally.db"
    monkeypatch.setenv("DB_PATH", str(path))
    db.init_db()
    assert path.exists()
    assert table_names(path) == TABLES
    assert db.get_cash() == 10000.0
    assert db.watchlist_tickers() == ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def test_init_is_idempotent_and_keeps_user_data(temp_db):
    db.init_db()
    db.set_cash(123.0)
    db.remove_from_watchlist("AAPL")
    db.init_db()
    assert db.get_cash() == 123.0
    assert "AAPL" not in db.watchlist_tickers()
    assert len(db.watchlist_tickers()) == 9


def test_emptied_watchlist_is_not_reseeded(temp_db):
    db.init_db()
    for t in db.watchlist_tickers():
        db.remove_from_watchlist(t)
    db.init_db()
    assert db.watchlist_tickers() == []


def test_init_seeds_a_file_with_tables_but_no_user(temp_db):
    with sqlite3.connect(temp_db) as conn:
        conn.executescript(db.schema.SCHEMA)
    db.init_db()
    assert db.get_cash() == 10000.0
    assert len(db.watchlist_tickers()) == 10


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        ("INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES ('x', 'default', 'AAPL', 't')", ()),
        (
            "INSERT INTO positions (id, ticker, quantity, avg_cost, updated_at) VALUES (?, ?, 1, 1, 't')",
            ("p2", "AAPL"),
        ),
    ],
)
def test_unique_per_user_and_ticker(temp_db, sql, params):
    db.init_db()
    db.upsert_position("AAPL", 1, 1)
    with sqlite3.connect(temp_db) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, params)


def test_user_id_defaults_to_default(temp_db):
    db.init_db()
    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO trades (id, ticker, side, quantity, price, executed_at) VALUES ('t', 'X', 'buy', 1, 1, 'now')"
        )
        assert conn.execute("SELECT user_id FROM trades").fetchone()[0] == "default"
