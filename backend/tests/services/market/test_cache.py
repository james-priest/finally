import asyncio

import pytest

from app.services.market import PriceCache, PriceUpdate


def test_update_tracks_previous_price_and_direction():
    cache = PriceCache()
    first = cache.update("AAPL", 190.0)
    assert (first.price, first.previous_price, first.direction) == (190.0, 190.0, "flat")
    second = cache.update("AAPL", 191.234)
    assert second.price == 191.23  # rounded to cents
    assert second.previous_price == 190.0
    assert second.direction == "up"
    assert cache.update("AAPL", 190.5).direction == "down"
    assert cache.version == 3


def test_prev_close_defaults_to_first_price_then_carries_forward():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    assert cache.update("AAPL", 195.0).prev_close == 190.0
    assert cache.update("AAPL", 196.0, prev_close=193.0).prev_close == 193.0
    assert cache.update("AAPL", 197.0).prev_close == 193.0


@pytest.mark.parametrize("bad", [0, -1.0, float("nan"), float("inf")])
def test_rejects_invalid_prices(bad):
    with pytest.raises(ValueError):
        PriceCache().update("AAPL", bad)


def test_remove_bumps_version_only_when_present():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.remove("MSFT")
    assert cache.version == 1
    cache.remove("AAPL")
    assert cache.version == 2
    assert cache.get("AAPL") is None
    assert cache.get_price("AAPL") is None


def test_to_dict_is_the_sse_contract():
    update = PriceUpdate("AAPL", price=189.95, previous_price=190.0, prev_close=190.0, timestamp=1.23456)
    assert update.to_dict() == {
        "ticker": "AAPL",
        "price": 189.95,
        "previous_price": 190.0,
        "prev_close": 190.0,
        "change": -0.05,
        "day_change_percent": -0.0263,
        "direction": "down",
        "timestamp": 1.235,
    }
    assert PriceUpdate("X", 1.0, 1.0, prev_close=0.0, timestamp=0).day_change_percent == 0.0


async def test_wait_for_change_returns_at_once_when_version_differs():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    assert await cache.wait_for_change(0) == 1


async def test_wait_for_change_wakes_on_update():
    cache = PriceCache()
    waiter = asyncio.create_task(cache.wait_for_change(cache.version))
    await asyncio.sleep(0)
    assert not waiter.done()
    cache.update("AAPL", 190.0)
    assert await asyncio.wait_for(waiter, 1) == 1
