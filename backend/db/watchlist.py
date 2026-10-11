"""The watchlist, and the tracked set the market data source prices (watchlist plus open positions)."""

import sqlite3

from db.connection import USER_ID, connect, new_id, now


def list_watchlist() -> list[dict]:
    """Watchlist entries in insertion order: {ticker, added_at}."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT ticker, added_at FROM watchlist WHERE user_id = ? ORDER BY rowid", (USER_ID,)
        ).fetchall()
    return [dict(r) for r in rows]


def watchlist_tickers() -> list[str]:
    return [entry["ticker"] for entry in list_watchlist()]


def in_watchlist(ticker: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM watchlist WHERE user_id = ? AND ticker = ?", (USER_ID, ticker)).fetchone()
    return row is not None


def add_to_watchlist(ticker: str) -> dict | None:
    """Add a ticker and return its entry {ticker, added_at}, or None if it was already there."""
    entry = {"ticker": ticker, "added_at": now()}
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                (new_id(), USER_ID, ticker, entry["added_at"]),
            )
    except sqlite3.IntegrityError:  # UNIQUE (user_id, ticker)
        return None
    return entry


def remove_from_watchlist(ticker: str) -> bool:
    """Remove a ticker. False if it was not on the watchlist."""
    with connect() as conn:
        cur = conn.execute("DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (USER_ID, ticker))
    return cur.rowcount > 0


def tracked_tickers() -> list[str]:
    """Tickers the market data source should price: the watchlist plus every open position, sorted."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT ticker FROM watchlist WHERE user_id = ?
            UNION
            SELECT ticker FROM positions WHERE user_id = ? AND quantity > 0
            ORDER BY ticker
            """,
            (USER_ID, USER_ID),
        ).fetchall()
    return [r["ticker"] for r in rows]
