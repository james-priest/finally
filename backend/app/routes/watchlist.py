from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dependencies import MarketSourceDep, PriceCacheDep
from app.routes.tickers import parse_ticker
from app.services import watchlist
from app.services.watchlist import WatchlistError

router = APIRouter()


class WatchlistAdd(BaseModel):
    ticker: str


@router.get("/api/watchlist")
async def get_watchlist(cache: PriceCacheDep) -> dict:
    return {"tickers": watchlist.list_watchlist(cache)}


@router.post("/api/watchlist", status_code=201)
async def add_to_watchlist(body: WatchlistAdd, source: MarketSourceDep, cache: PriceCacheDep) -> dict:
    try:
        return await watchlist.add_ticker(parse_ticker(body.ticker), source, cache)
    except WatchlistError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.delete("/api/watchlist/{ticker}", status_code=204)
async def remove_from_watchlist(ticker: str, source: MarketSourceDep) -> None:
    try:
        await watchlist.remove_ticker(parse_ticker(ticker), source)
    except WatchlistError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
