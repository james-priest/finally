"""Chat history with the LLM. `actions` is stored as JSON and returned decoded."""

import json
import sqlite3
from typing import Any, Literal

from db.connection import USER_ID, connect, new_id, now


def insert_chat_message(
    role: Literal["user", "assistant"], content: str, actions: dict[str, Any] | None = None
) -> dict:
    """Store a message and return it as {id, role, content, actions, created_at}."""
    message = {"id": new_id(), "role": role, "content": content, "actions": actions, "created_at": now()}
    with connect() as conn:
        conn.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                message["id"],
                USER_ID,
                role,
                content,
                json.dumps(actions) if actions is not None else None,
                message["created_at"],
            ),
        )
    return message


def list_chat_messages(limit: int | None = None) -> list[dict]:
    """The most recent `limit` messages (all if None), oldest first."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM (
                SELECT rowid, id, role, content, actions, created_at FROM chat_messages
                WHERE user_id = ? ORDER BY rowid DESC LIMIT ?
            ) ORDER BY rowid
            """,
            (USER_ID, -1 if limit is None else limit),
        ).fetchall()
    return [_message(r) for r in rows]


def _message(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "actions": json.loads(row["actions"]) if row["actions"] is not None else None,
        "created_at": row["created_at"],
    }
