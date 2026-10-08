import asyncio
import math
import random
import statistics

import pytest

from app.services.market import PriceCache
from app.services.market.simulator import GBMSimulator, SimulatorDataSource, profile_for


def test_unknown_ticker_gets_stable_profile():
    p = profile_for("PYPL")
    assert p == profile_for("PYPL")
    assert 50 <= p.seed_price < 300
    assert (p.volatility, p.drift, p.sector) == (0.30, 0.08, "PYPL")


def test_rejects_weights_above_one():
    with pytest.raises(ValueError):
        GBMSimulator(market_weight=0.6, sector_weight=0.5)


def test_simulator_is_deterministic_with_seed():
    a = GBMSimulator(rng=random.Random(1))
    b = GBMSimulator(rng=random.Random(1))
    for sim in (a, b):
        sim.add("AAPL")
        sim.add("PYPL")
    assert [a.step() for _ in range(5)] == [b.step() for _ in range(5)]


def test_removed_ticker_resumes_its_last_price():
    sim = GBMSimulator(rng=random.Random(2))
    sim.add("AAPL")
    for _ in range(10):
        sim.step()
    last = sim.step()["AAPL"]
    sim.remove("AAPL")
    assert "AAPL" not in sim
    assert sim.add("AAPL") == last


def test_volatility_and_correlations_match_the_model():
    sim = GBMSimulator(event_probability=0.0, rng=random.Random(42))
    for t in ("AAPL", "MSFT", "JPM", "PYPL"):
        sim.add(t)
    prev = sim.step()
    returns: dict[str, list[float]] = {t: [] for t in prev}
    for _ in range(20_000):
        cur = sim.step()
        for t in cur:
            returns[t].append(math.log(cur[t] / prev[t]))
        prev = cur
    assert statistics.stdev(returns["AAPL"]) == pytest.approx(0.25 * math.sqrt(sim.dt), rel=0.03)
    assert statistics.correlation(returns["AAPL"], returns["MSFT"]) == pytest.approx(0.6, abs=0.03)  # same sector
    assert statistics.correlation(returns["AAPL"], returns["JPM"]) == pytest.approx(0.3, abs=0.03)  # market only
    assert statistics.correlation(returns["AAPL"], returns["PYPL"]) == pytest.approx(0.3, abs=0.03)  # unknown ticker


def test_jump_events_happen_at_the_configured_rate():
    sim = GBMSimulator(rng=random.Random(7))
    for t in ("AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"):
        sim.add(t)
    prev, jumps = sim.step(), 0
    for _ in range(20_000):
        cur = sim.step()
        jumps += sum(abs(math.log(cur[t] / prev[t])) > 0.015 for t in cur)  # diffusion alone is < 0.5%
        prev = cur
    assert 70 <= jumps <= 130  # expected 10 tickers x 20,000 ticks x 0.0005 = 100


async def test_source_seeds_on_start_then_ticks():
    cache = PriceCache()
    source = SimulatorDataSource(cache, tick_seconds=0.01)
    await source.start(["AAPL", "MSFT"])
    assert cache.get_price("AAPL") == 190.0  # priced before the first tick
    await asyncio.sleep(0.1)
    assert cache.version > 10
    assert cache.get("AAPL").prev_close == 190.0  # day change is measured from the seed price
    await source.stop()


async def test_source_add_and_remove_ticker():
    cache = PriceCache()
    source = SimulatorDataSource(cache, tick_seconds=0.01)
    await source.start(["AAPL"])
    await source.add_ticker("PYPL")
    assert cache.get_price("PYPL") == profile_for("PYPL").seed_price
    await asyncio.sleep(0.05)
    await source.remove_ticker("PYPL")
    assert cache.get("PYPL") is None
    assert source.get_tickers() == ["AAPL"]
    await source.stop()


async def test_stop_halts_ticks_and_is_idempotent():
    cache = PriceCache()
    source = SimulatorDataSource(cache, tick_seconds=0.01)
    await source.start(["AAPL"])
    await asyncio.sleep(0.03)
    await source.stop()
    await source.stop()
    version = cache.version
    await asyncio.sleep(0.03)
    assert cache.version == version


async def test_re_added_ticker_resumes_its_price_and_keeps_the_seed_as_prev_close():
    cache = PriceCache()
    source = SimulatorDataSource(cache, simulator=GBMSimulator(rng=random.Random(3)), tick_seconds=60)
    await source.start(["AAPL"])
    for _ in range(50):
        source._sim.step()
    last = source._sim.step()["AAPL"]
    await source.remove_ticker("AAPL")
    await source.add_ticker("AAPL")
    update = cache.get("AAPL")
    assert update.price == round(last, 2)  # no jump back to the seed price
    assert update.prev_close == 190.0  # day change is still measured from the seed price
    await source.stop()


async def test_source_survives_a_failing_tick():
    class FlakySimulator(GBMSimulator):
        failed = False

        def step(self):
            if not self.failed:
                self.failed = True
                raise RuntimeError("boom")
            return super().step()

    cache = PriceCache()
    source = SimulatorDataSource(cache, tick_seconds=0.01, simulator=FlakySimulator(tick_seconds=0.01))
    await source.start(["AAPL"])
    await asyncio.sleep(0.1)
    assert source._sim.failed
    assert cache.version > 3  # ticks carried on after the failure
    await source.stop()


async def test_start_twice_runs_one_task_and_add_ticker_is_idempotent():
    cache = PriceCache()
    source = SimulatorDataSource(cache, tick_seconds=60)
    await source.start(["AAPL"])
    await source.start(["AAPL"])
    assert sum(t.get_name() == "market-simulator" for t in asyncio.all_tasks()) == 1
    version = cache.version
    await source.add_ticker("AAPL")
    assert cache.version == version  # already tracked: no new cache write
    await source.stop()
