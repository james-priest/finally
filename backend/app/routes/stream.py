from collections.abc import AsyncIterable

from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.dependencies import PriceCacheDep

router = APIRouter()

RECONNECT_MS = 1000  # how long the browser waits before reconnecting a dropped stream


@router.get("/api/stream/prices", response_class=EventSourceResponse)
async def stream_prices(cache: PriceCacheDep) -> AsyncIterable[ServerSentEvent]:
    """Every tracked ticker's price on connect, then again after each cache change."""
    version = -1  # never equal to cache.version, so the first event goes out immediately
    retry: int | None = RECONNECT_MS  # sent once; the browser remembers it
    while True:
        version = await cache.wait_for_change(version)
        yield ServerSentEvent(data={t: u.to_dict() for t, u in cache.all().items()}, retry=retry)
        retry = None
