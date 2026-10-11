"""Portfolio value over time, for the P&L chart."""

from db.connection import USER_ID, connect, new_id, now


def insert_snapshot(total_value: float) -> dict:
    """Record the portfolio's total value now. Returns {total_value, recorded_at}."""
    snapshot = {"total_value": total_value, "recorded_at": now()}
    with connect() as conn:
        conn.execute(
            "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, ?, ?, ?)",
            (new_id(), USER_ID, total_value, snapshot["recorded_at"]),
        )
    return snapshot


def list_snapshots() -> list[dict]:
    """All snapshots oldest first: {total_value, recorded_at}."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT total_value, recorded_at FROM portfolio_snapshots WHERE user_id = ? ORDER BY rowid",
            (USER_ID,),
        ).fetchall()
    return [dict(r) for r in rows]
