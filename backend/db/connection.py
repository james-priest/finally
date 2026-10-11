"""SQLite file location, connections, and the row helpers every query module shares."""

import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

USER_ID = "default"  # single-user for now; every table already carries user_id

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "db" / "finally.db"  # repo-root db/ (Docker: /app/db)


def db_path() -> Path:
    """The SQLite file: env DB_PATH, read on every call so tests can point it at a temp file."""
    return Path(os.environ.get("DB_PATH") or DEFAULT_DB_PATH)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection for one unit of work: commit on success, roll back on error, always close.

    A fresh connection per call keeps the layer safe to use from `asyncio.to_thread` workers.
    """
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            yield conn


def now() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())
