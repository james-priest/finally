import asyncio
import json
import socket

import httpx
import uvicorn
from fastapi import FastAPI

from app.routes import stream
from app.services.market import PriceCache


async def test_stream_sends_full_state_then_every_change():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    app = FastAPI()
    app.state.price_cache = cache
    app.include_router(stream.router)

    with socket.socket() as s:  # find a free port
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            async with client.stream("GET", f"http://127.0.0.1:{port}/api/stream/prices") as resp:
                assert resp.headers["content-type"].startswith("text/event-stream")
                assert resp.headers["cache-control"] == "no-cache"
                lines = resp.aiter_lines()

                async def next_event() -> dict[str, str]:
                    """Read up to the blank line that ends an event; return its fields."""
                    event: dict[str, str] = {}
                    async for line in lines:
                        if line:
                            field, _, value = line.partition(": ")
                            event[field] = value
                        elif "data" in event:
                            return event

                first = await next_event()
                assert first["retry"] == "1000"  # reconnect hint, sent once
                prices = json.loads(first["data"])
                assert (prices["AAPL"]["price"], prices["AAPL"]["direction"]) == (190.0, "flat")

                cache.update("AAPL", 190.5)
                prices = json.loads((await next_event())["data"])
                assert (prices["AAPL"]["previous_price"], prices["AAPL"]["direction"]) == (190.0, "up")

                cache.remove("AAPL")
                cache.update("MSFT", 420.0)
                third = await next_event()
                assert list(json.loads(third["data"])) == ["MSFT"]  # removed tickers drop out
                assert "retry" not in third
    finally:
        server.should_exit = True
        await serving
