from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.dependencies import MarketSourceDep
from app.routes import stream
from app.services.market import PriceCache, create_market_data_source

# Placeholder until the database layer exists: it should return watchlist ∪ open positions.
DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def tracked_tickers() -> list[str]:
    return list(DEFAULT_TICKERS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(tracked_tickers())
    app.state.price_cache = cache
    app.state.market_source = source
    try:
        yield
    finally:
        await source.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(stream.router)


@app.get("/api/health")
async def health(source: MarketSourceDep) -> dict:
    return {"status": "ok", "market_data": source.status()}
