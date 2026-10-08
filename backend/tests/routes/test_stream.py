import asyncio
import json
import socket

import httpx
import uvicorn
from fastapi import FastAPI

from app.routes import stream
from app.services.market import PriceCache


def stream_app(cache: PriceCache) -> FastAPI:
    app = FastAPI()
    app.state.price_cache = cache
    app.include_router(stream.router)
    return app


async def start_server(app: FastAPI, **config) -> tuple[uvicorn.Server, asyncio.Task, str]:
    """Serve `app` with a real uvicorn on a free port; return the server, its task and the stream URL."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning", **config))
    serving = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 - uvicorn exposes only this flag
        await asyncio.sleep(0.01)
    return server, serving, f"http://127.0.0.1:{port}/api/stream/prices"


async def test_stream_sends_full_state_then_every_change():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    server, serving, url = await start_server(stream_app(cache))

    try:
        async with httpx.AsyncClient(timeout=5) as client, client.stream("GET", url) as resp:
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
                raise AssertionError("stream ended")

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


async def test_graceful_shutdown_timeout_closes_open_streams():
    # The stream never ends on its own, so the server must run with --timeout-graceful-shutdown
    # (see app/main.py); otherwise a shutdown waits for every open browser tab.
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    server, serving, url = await start_server(stream_app(cache), timeout_graceful_shutdown=0.2)
    connected = asyncio.Event()

    async def listen():
        async with httpx.AsyncClient(timeout=5) as client, client.stream("GET", url) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    connected.set()

    listener = asyncio.create_task(listen())
    await asyncio.wait_for(connected.wait(), 5)
    server.should_exit = True
    await asyncio.wait_for(serving, 5)  # finishes although the client is still connected
    listener.cancel()
    await asyncio.gather(listener, return_exceptions=True)
