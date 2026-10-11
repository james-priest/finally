import httpx
import pytest

from app.main import app


@pytest.fixture
async def client(monkeypatch):
    """The real app (temp DB, simulator) behind an in-process httpx client."""
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
