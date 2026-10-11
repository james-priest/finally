"""Cash, positions and trades. `record_trade` writes all three for one fill in a single transaction."""

import sqlite3
from typing import Literal

from db.connection import USER_ID, connect, new_id, now


def get_cash() -> float:
    with connect() as conn:
        row = conn.execute("SELECT cash_balance FROM users_profile WHERE id = ?", (USER_ID,)).fetchone()
    return row["cash_balance"]


def set_cash(cash: float) -> None:
    with connect() as conn:
        conn.execute("UPDATE users_profile SET cash_balance = ? WHERE id = ?", (cash, USER_ID))


def get_positions() -> list[dict]:
    """Open positions sorted by ticker: {ticker, quantity, avg_cost, updated_at}."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions WHERE user_id = ? ORDER BY ticker",
            (USER_ID,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_position(ticker: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions WHERE user_id = ? AND ticker = ?",
            (USER_ID, ticker),
        ).fetchone()
    return dict(row) if row else None


def upsert_position(ticker: str, quantity: float, avg_cost: float) -> None:
    with connect() as conn:
        _upsert_position(conn, ticker, quantity, avg_cost)


def delete_position(ticker: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM positions WHERE user_id = ? AND ticker = ?", (USER_ID, ticker))


def insert_trade(ticker: str, side: Literal["buy", "sell"], quantity: float, price: float) -> dict:
    """Append to the trade log only. For a real fill use `record_trade`."""
    with connect() as conn:
        return _insert_trade(conn, ticker, side, quantity, price)


def record_trade(
    ticker: str,
    side: Literal["buy", "sell"],
    quantity: float,
    price: float,
    cash: float,
    position: tuple[float, float] | None,
) -> dict:
    """Persist one fill atomically: log the trade, set cash, and set or delete the position.

    `cash` and `position` (quantity, avg_cost) are the new values after the fill, already
    validated by the caller; `position=None` deletes the row. Returns the trade dict.
    """
    with connect() as conn:
        trade = _insert_trade(conn, ticker, side, quantity, price)
        conn.execute("UPDATE users_profile SET cash_balance = ? WHERE id = ?", (cash, USER_ID))
        if position is None:
            conn.execute("DELETE FROM positions WHERE user_id = ? AND ticker = ?", (USER_ID, ticker))
        else:
            _upsert_position(conn, ticker, *position)
    return trade


def _upsert_position(conn: sqlite3.Connection, ticker: str, quantity: float, avg_cost: float) -> None:
    conn.execute(
        """
        INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (user_id, ticker) DO UPDATE SET
            quantity = excluded.quantity, avg_cost = excluded.avg_cost, updated_at = excluded.updated_at
        """,
        (new_id(), USER_ID, ticker, quantity, avg_cost, now()),
    )


def _insert_trade(conn: sqlite3.Connection, ticker: str, side: str, quantity: float, price: float) -> dict:
    trade = {
        "id": new_id(),
        "ticker": ticker,
        "side": side,
        "quantity": float(quantity),
        "price": float(price),
        "executed_at": now(),
    }
    conn.execute(
        "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (trade["id"], USER_ID, ticker, side, quantity, price, trade["executed_at"]),
    )
    return trade
