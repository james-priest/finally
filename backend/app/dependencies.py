from typing import Annotated

from fastapi import Depends, Request

from app.services.market import MarketDataSource, PriceCache


def get_price_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache


def get_market_source(request: Request) -> MarketDataSource:
    return request.app.state.market_source


PriceCacheDep = Annotated[PriceCache, Depends(get_price_cache)]
MarketSourceDep = Annotated[MarketDataSource, Depends(get_market_source)]
