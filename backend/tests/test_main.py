import asyncio

import httpx

from app.main import app


async def test_lifespan_starts_the_market_source_and_health_reports_it(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "market_data": {"source": "simulator", "tickers": 10}}
        assert app.state.price_cache.get_price("AAPL") == 190.0  # priced before the first request
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "market-simulator"]  # stopped on shutdown
