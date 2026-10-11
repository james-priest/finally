import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import db
from app.dependencies import MarketSourceDep
from app.routes import chat, portfolio, stream, watchlist
from app.services.market import PriceCache, create_market_data_source
from app.services.portfolio import run_snapshots

# uvicorn configures only its own loggers; without this the app's INFO lines are dropped
# and its warnings print with no level or logger name.
logging.basicConfig(level=logging.INFO, format="%(levelname)-9s %(name)s: %(message)s")

# Run with `uvicorn app.main:app --timeout-graceful-shutdown 2`. SSE streams never end on
# their own, so without the timeout a shutdown waits for every browser tab to disconnect.


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(db.init_db)  # creates and seeds the SQLite file on first run
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(await asyncio.to_thread(db.tracked_tickers))
    app.state.price_cache = cache
    app.state.market_source = source
    snapshots = asyncio.create_task(run_snapshots(cache), name="portfolio-snapshots")
    try:
        yield
    finally:
        snapshots.cancel()
        with suppress(asyncio.CancelledError):
            await snapshots
        await source.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(stream.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(chat.router)


@app.get("/api/health")
async def health(source: MarketSourceDep) -> dict:
    return {"status": "ok", "market_data": source.status()}


# The Next.js static export. Mounted last so every /api route above takes precedence.
STATIC_DIR = Path(os.environ.get("STATIC_DIR") or Path(__file__).resolve().parents[1] / "static")
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
