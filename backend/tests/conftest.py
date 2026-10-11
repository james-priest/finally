import pytest


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Every test gets its own empty SQLite file, so nothing touches the real db/finally.db."""
    path = tmp_path / "finally.db"
    monkeypatch.setenv("DB_PATH", str(path))
    return path
