"""Lazy initialization: create the tables and seed the default user on first run."""

from pathlib import Path

from db.connection import USER_ID, connect, new_id, now

SCHEMA = (Path(__file__).parent / "schema.sql").read_text()

DEFAULT_CASH = 10000.0
DEFAULT_WATCHLIST = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def init_db() -> None:
    """Create missing tables, and seed the user and default watchlist if the user does not exist yet.

    Idempotent. Seeding is keyed on the user row, so a watchlist the user emptied stays empty.
    """
    with connect() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT 1 FROM users_profile WHERE id = ?", (USER_ID,)).fetchone():
            return
        created = now()
        conn.execute(
            "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
            (USER_ID, DEFAULT_CASH, created),
        )
        conn.executemany(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            [(new_id(), USER_ID, t, created) for t in DEFAULT_WATCHLIST],
        )
