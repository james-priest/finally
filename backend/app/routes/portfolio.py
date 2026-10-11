from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import MarketSourceDep, PriceCacheDep
from app.routes.tickers import parse_ticker
from app.services import portfolio
from app.services.portfolio import Side, TradeError

router = APIRouter()


class TradeRequest(BaseModel):
    ticker: str
    quantity: Annotated[float, Field(gt=0)]
    side: Side


@router.get("/api/portfolio")
async def get_portfolio(cache: PriceCacheDep) -> dict:
    return portfolio.get_portfolio(cache)


@router.post("/api/portfolio/trade")
async def trade(body: TradeRequest, source: MarketSourceDep, cache: PriceCacheDep) -> dict:
    ticker = parse_ticker(body.ticker)
    try:
        executed = await portfolio.execute_trade(ticker, body.side, body.quantity, source, cache)
    except TradeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"trade": executed, "portfolio": portfolio.get_portfolio(cache)}


@router.get("/api/portfolio/history")
async def history() -> dict:
    return {"snapshots": portfolio.get_history()}
