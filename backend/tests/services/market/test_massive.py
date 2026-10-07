import asyncio
import threading
from datetime import date

import pytest
from massive.exceptions import BadResponse
from massive.rest.models import Agg, GroupedDailyAgg, LastTrade, MinuteSnapshot, TickerSnapshot
from urllib3.exceptions import MaxRetryError

from app.services.market import PriceCache
from app.services.market import massive as massive_module
from app.services.market.massive import (
    MAX_EOD_LOOKUPS,
    MassiveDataSource,
    is_not_authorized,
    snapshot_price,
)

NOT_AUTHORIZED = '{"status":"NOT_AUTHORIZED","request_id":"x","message":"You are not entitled to this data."}'


class FakeClient:
    """Stands in for massive.RESTClient: canned responses, and a log of every call."""

    def __init__(self, snapshots=(), grouped=None, snapshot_error=None):
        self.snapshots = {s.ticker: s for s in snapshots}
        self.grouped = grouped or {}  # "YYYY-MM-DD" -> bars, or an exception to raise
        self.snapshot_error = snapshot_error
        self.calls = []

    def get_snapshot_all(self, market_type, tickers):
        self.calls.append(("snapshot", *tickers))
        if self.snapshot_error:
            raise self.snapshot_error
        return [self.snapshots[t] for t in tickers if t in self.snapshots]

    def get_grouped_daily_aggs(self, day):
        self.calls.append(("grouped", day))
        result = self.grouped.get(day, [])
        if isinstance(result, Exception):
            raise result
        return result


def snap(ticker, last=None, minute=None, day=None, prev=None):
    return TickerSnapshot(
        ticker=ticker,
        last_trade=LastTrade(price=last) if last is not None else None,
        min=MinuteSnapshot(close=minute) if minute is not None else None,
        day=Agg(close=day) if day is not None else None,
        prev_day=Agg(close=prev) if prev is not None else None,
    )


def bars(**closes):
    return [GroupedDailyAgg(ticker=t, close=c) for t, c in closes.items()]


@pytest.fixture
def monday(monkeypatch):
    monkeypatch.setattr(massive_module, "us_market_today", lambda: date(2026, 10, 5))


def test_real_client_has_no_hidden_retries():
    # The client's own retries obey Retry-After on 429 and spend the free plan's calls.
    assert MassiveDataSource(PriceCache(), "key")._client.retries == 0


def test_snapshot_price_fallback_order():
    assert snapshot_price(snap("A", last=10, minute=9, day=8, prev=7)) == 10
    assert snapshot_price(snap("A", minute=9, day=8, prev=7)) == 9  # Starter plan: no last trade
    assert snapshot_price(snap("A", minute=0, day=0, prev=7)) == 7  # early morning: bars are reset
    assert snapshot_price(snap("A")) is None


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (NOT_AUTHORIZED, True),
        ('{"status":"ERROR","message":"You are not entitled to this data."}', True),
        ('{"status":"ERROR","request_id":"x","error":"Unknown API Key"}', False),
        ("<html>502 Bad Gateway</html>", False),
        ("null", False),
    ],
)
def test_is_not_authorized(body, expected):
    assert is_not_authorized(BadResponse(body)) is expected


async def test_start_polls_all_tickers_in_one_call():
    client = FakeClient([snap("AAPL", minute=191.5, prev=189.0), snap("MSFT", last=421.0, prev=420.0)])
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", client=client)
    await source.start(["MSFT", "AAPL", "XYZQ"])
    assert client.calls == [("snapshot", "AAPL", "MSFT", "XYZQ")]
    assert (cache.get("AAPL").price, cache.get("AAPL").prev_close) == (191.5, 189.0)
    assert cache.get("XYZQ") is None  # unknown tickers are left out of the response
    assert source.status()["mode"] == "snapshot"
    await source.stop()


async def test_add_ticker_is_priced_right_away():
    client = FakeClient([snap("AAPL", minute=191.5), snap("PYPL", minute=61.2, prev=60.0)])
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", client=client)
    await source.start(["AAPL"])
    await source.add_ticker("PYPL")
    await source.add_ticker("PYPL")  # already tracked: no call
    assert client.calls[1:] == [("snapshot", "PYPL")]
    assert cache.get_price("PYPL") == 61.2
    await source.stop()


async def test_ticker_removed_during_a_poll_is_not_written_back():
    class GatedClient(FakeClient):
        gate, waiting = threading.Event(), threading.Event()

        def get_snapshot_all(self, market_type, tickers):
            self.waiting.set()
            self.gate.wait(5)
            return super().get_snapshot_all(market_type, tickers)

    client = GatedClient([snap("AAPL", minute=191.5), snap("MSFT", minute=421.0)])
    client.gate.set()
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", poll_seconds=0.01, client=client)
    await source.start(["AAPL", "MSFT"])
    client.gate.clear()
    client.waiting.clear()
    await asyncio.to_thread(client.waiting.wait, 5)  # a background poll is now in flight
    await source.remove_ticker("MSFT")
    client.gate.set()
    await asyncio.sleep(0.05)
    assert cache.get("MSFT") is None
    assert cache.get_price("AAPL") == 191.5
    await source.stop()


async def test_free_plan_falls_back_to_end_of_day_prices(monday):
    client = FakeClient(
        snapshot_error=BadResponse(NOT_AUTHORIZED),
        grouped={"2026-10-02": bars(AAPL=192.0, MSFT=420.0), "2026-10-01": bars(AAPL=190.0, MSFT=415.0)},
    )
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", client=client)
    await source.start(["AAPL"])
    # one snapshot probe, then Friday and Thursday; the weekend costs no calls
    assert client.calls == [("snapshot", "AAPL"), ("grouped", "2026-10-02"), ("grouped", "2026-10-01")]
    assert source.status()["mode"] == "eod"
    assert (cache.get("AAPL").price, cache.get("AAPL").prev_close) == (192.0, 190.0)
    await source.add_ticker("MSFT")  # served from the stored EOD data, no extra call
    assert cache.get_price("MSFT") == 420.0
    assert len(client.calls) == 3
    await source.stop()


async def test_eod_skips_holidays_and_days_the_plan_cannot_see(monkeypatch):
    monkeypatch.setattr(massive_module, "us_market_today", lambda: date(2026, 9, 9))  # a Wednesday
    client = FakeClient(
        snapshot_error=BadResponse(NOT_AUTHORIZED),
        grouped={
            "2026-09-08": BadResponse(NOT_AUTHORIZED),  # Tuesday: not on this plan (yet)
            "2026-09-07": [],  # Monday: Labor Day, market closed
            "2026-09-04": bars(AAPL=192.0),  # Friday
            "2026-09-03": bars(AAPL=190.0),  # Thursday
        },
    )
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", client=client)
    await source.start(["AAPL"])
    assert [day for _, day in client.calls[1:]] == ["2026-09-08", "2026-09-07", "2026-09-04", "2026-09-03"]
    assert (cache.get("AAPL").price, cache.get("AAPL").prev_close) == (192.0, 190.0)
    await source.stop()


async def test_eod_with_one_session_uses_its_close_as_prev_close(monday):
    client = FakeClient(snapshot_error=BadResponse(NOT_AUTHORIZED), grouped={"2026-10-02": bars(AAPL=192.0)})
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", client=client)
    await source.start(["AAPL"])
    assert (cache.get("AAPL").price, cache.get("AAPL").prev_close) == (192.0, 192.0)
    assert source.status()["last_error"] is None
    await source.stop()


async def test_eod_lookups_are_capped(monday):
    client = FakeClient(snapshot_error=BadResponse(NOT_AUTHORIZED))  # no grouped data at all
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", client=client)
    await source.start(["AAPL"])
    assert len(client.calls) == 1 + MAX_EOD_LOOKUPS  # stays within the free plan's 5 calls/min
    assert "no grouped daily bars" in source.status()["last_error"]
    assert cache.get("AAPL") is None
    await source.stop()


async def test_failures_back_off_and_recover():
    client = FakeClient(snapshot_error=BadResponse('{"status":"ERROR","error":"Unknown API Key"}'))
    source = MassiveDataSource(PriceCache(), "bad-key", poll_seconds=15, client=client)
    await source.start(["AAPL"])
    assert "Unknown API Key" in source.status()["last_error"]
    assert source.status()["mode"] == "snapshot"  # a bad key is not mistaken for the free plan
    assert source._next_delay() == 30
    await source._refresh()
    assert source._next_delay() == 60
    client.snapshot_error, client.snapshots = None, {"AAPL": snap("AAPL", minute=191.5)}
    await source._refresh()
    assert source._next_delay() == 15
    assert source.status()["last_error"] is None
    await source.stop()


async def test_downgrade_while_running_switches_to_eod(monday):
    client = FakeClient([snap("AAPL", minute=191.5)], grouped={"2026-10-02": bars(AAPL=192.0)})
    cache = PriceCache()
    source = MassiveDataSource(cache, "key", poll_seconds=2, client=client)  # fast polling on a paid plan
    await source.start(["AAPL"])
    client.snapshot_error = BadResponse(NOT_AUTHORIZED)  # the plan is downgraded
    await source._refresh()  # the next background poll
    assert source.status()["mode"] == "eod"
    assert cache.get_price("AAPL") == 192.0
    await source.stop()


async def test_free_plan_retries_at_most_once_a_minute(monday):
    client = FakeClient(snapshot_error=BadResponse(NOT_AUTHORIZED))  # no EOD data either: refreshes fail
    source = MassiveDataSource(PriceCache(), "key", poll_seconds=2, client=client)  # left over from a paid plan
    await source.start(["AAPL"])
    assert source._next_delay() == 60  # not 4s: the free plan allows 5 calls a minute
    await source.stop()


@pytest.mark.parametrize("error", [MaxRetryError(None, "/v2/snapshot", "refused"), KeyError("surprise")])
async def test_polling_survives_errors(error):
    client = FakeClient(snapshot_error=error)
    source = MassiveDataSource(PriceCache(), "key", poll_seconds=0.001, client=client)
    await source.start(["AAPL"])
    await asyncio.sleep(0.05)
    assert len(client.calls) >= 3  # the background loop kept polling after the first failure
    await source.stop()
