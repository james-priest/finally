import importlib

import httpx

import app.main


async def test_static_frontend_is_served_after_the_api_routes(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>FinAlly</html>")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    module = importlib.reload(app.main)  # STATIC_DIR is read at import time
    try:
        async with module.app.router.lifespan_context(module.app):
            transport = httpx.ASGITransport(app=module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                assert (await client.get("/")).text == "<html>FinAlly</html>"
                assert (await client.get("/api/health")).json()["status"] == "ok"
                assert (await client.get("/api/watchlist")).status_code == 200
    finally:
        monkeypatch.undo()
        importlib.reload(app.main)
