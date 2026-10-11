"""FinAlly's SQLite layer (PLAN.md §7).

Plain synchronous functions on stdlib sqlite3, one connection per call. From async code, call them
through `asyncio.to_thread`. Tickers are stored as given: normalize them before calling.
"""

from db.chat import insert_chat_message, list_chat_messages
from db.connection import db_path
from db.portfolio import (
    delete_position,
    get_cash,
    get_position,
    get_positions,
    insert_trade,
    record_trade,
    set_cash,
    upsert_position,
)
from db.schema import DEFAULT_CASH, DEFAULT_WATCHLIST, init_db
from db.snapshots import insert_snapshot, list_snapshots
from db.watchlist import (
    add_to_watchlist,
    in_watchlist,
    list_watchlist,
    remove_from_watchlist,
    tracked_tickers,
    watchlist_tickers,
)

__all__ = [
    "DEFAULT_CASH",
    "DEFAULT_WATCHLIST",
    "add_to_watchlist",
    "db_path",
    "delete_position",
    "get_cash",
    "get_position",
    "get_positions",
    "in_watchlist",
    "init_db",
    "insert_chat_message",
    "insert_snapshot",
    "insert_trade",
    "list_chat_messages",
    "list_snapshots",
    "list_watchlist",
    "record_trade",
    "remove_from_watchlist",
    "set_cash",
    "tracked_tickers",
    "upsert_position",
    "watchlist_tickers",
]
