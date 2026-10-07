import asyncio
import json
import logging
import time
from collections.abc import Iterable, Sequence
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta

from massive import RESTClient
from massive.exceptions import BadResponse
from massive.rest.models import TickerSnapshot
from urllib3.exceptions import HTTPError

from .base import MarketDataSource
from .cache import PriceCache

logger = logging.getLogger(__name__)

EOD_POLL_SECONDS = 3600.0  # free plan: closes change once a day
EOD_MIN_RETRY_SECONDS = 60.0  # free plan: 5 calls/min, so retry at most once a minute
MAX_BACKOFF_SECONDS = 300.0  # longest wait between attempts after repeated failures
MAX_EOD_LOOKUPS = 4  # grouped-daily calls per EOD refresh; the free plan allows 5 calls/min


class EndOfDayDataMissing(Exception):
    """No grouped daily bars were found for any recent trading day."""


def snapshot_price(snap: TickerSnapshot) -> float | None:
    """Best available price: last trade, then minute bar, then day bar, then previous close."""
    candidates = (
        snap.last_trade.price if snap.last_trade else None,
        snap.min.close if snap.min else None,
        snap.day.close if snap.day else None,
        snap.prev_day.close if snap.prev_day else None,
    )
    return next((p for p in candidates if p and p > 0), None)


def is_not_authorized(error: BadResponse) -> bool:
    """True when the key's plan does not include the requested data (HTTP 403 NOT_AUTHORIZED)."""
    try:
        body = json.loads(str(error))
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    message = str(body.get("message") or body.get("error") or "").lower()
    return body.get("status") == "NOT_AUTHORIZED" or "not entitled" in message


def us_market_today() -> date:
    """Today's date in New York, approximated as UTC-5 (never ahead of the real date)."""
    return (datetime.now(UTC) - timedelta(hours=5)).date()


class MassiveDataSource(MarketDataSource):
    """Polls the Massive REST API and writes prices into the cache.

    Snapshot mode (Starter plan and up): one Full Market Snapshot call per poll covers
    every tracked ticker. EOD mode (free Basic plan, detected from the first 403):
    closing prices from the grouped daily endpoint, refreshed hourly.
    """

    def __init__(
        self,
        cache: PriceCache,
        api_key: str,
        poll_seconds: float = 15.0,
        client: RESTClient | None = None,
    ) -> None:
        self._cache = cache
        # retries=0: the poll loop is the retry policy. The client's own retries obey
        # Retry-After on 429s, which can block a worker thread for minutes.
        self._client = client or RESTClient(
            api_key=api_key, connect_timeout=5.0, read_timeout=10.0, retries=0
        )
        self._poll_seconds = poll_seconds
        self._tickers: set[str] = set()
        self._eod_mode = False
        self._eod_closes: dict[str, tuple[float, float]] = {}  # ticker -> (close, previous close)
        self._failures = 0
        self._last_success: float | None = None
        self._last_error: str | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: Iterable[str]) -> None:
        self._tickers.update(tickers)
        await self._refresh()
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="massive-poller")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:
            return
        self._tickers.add(ticker)
        if self._eod_mode:
            self._write_eod(ticker)  # from the stored EOD data, no API call
        else:
            await self._refresh([ticker])  # one snapshot call, so the price is there right away

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self._tickers)

    def status(self) -> dict:
        return {
            "source": "massive",
            "mode": "eod" if self._eod_mode else "snapshot",
            "tickers": len(self._tickers),
            "last_success": self._last_success,
            "last_error": self._last_error,
        }

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._next_delay())
            await self._refresh()

    def _next_delay(self) -> float:
        if not self._failures:
            return EOD_POLL_SECONDS if self._eod_mode else self._poll_seconds
        delay = min(self._poll_seconds * 2**self._failures, MAX_BACKOFF_SECONDS)
        if self._eod_mode:  # also covers a low MASSIVE_POLL_SECONDS left over from a paid plan
            delay = max(delay, EOD_MIN_RETRY_SECONDS)
        return delay

    async def _refresh(self, tickers: Sequence[str] | None = None) -> None:
        """Poll once. Failures are logged and counted, never raised, so the loop never dies."""
        try:
            if self._eod_mode:
                await self._poll_eod()
            else:
                await self._poll_snapshot(self.get_tickers() if tickers is None else tickers)
        except BadResponse as e:
            if not self._eod_mode and is_not_authorized(e):
                logger.warning("Massive plan has no snapshot access; using end-of-day prices")
                self._eod_mode = True
                await self._refresh()
                return
            self._record_failure(f"Massive API error: {e}")
        except (HTTPError, EndOfDayDataMissing) as e:  # HTTPError: network, timeout, 429/5xx
            self._record_failure(f"Massive request failed: {e}")
        except Exception as e:
            logger.exception("Unexpected error while polling Massive")
            self._record_failure(f"Unexpected error: {e!r}")
        else:
            self._record_success()

    async def _poll_snapshot(self, tickers: Sequence[str]) -> None:
        if not tickers:
            return
        snapshots = await asyncio.to_thread(
            self._client.get_snapshot_all, "stocks", tickers=list(tickers)
        )
        for snap in snapshots:
            price = snapshot_price(snap)
            if price is None or snap.ticker not in self._tickers:
                continue  # no usable price, or removed while the request was in flight
            prev_close = snap.prev_day.close if snap.prev_day and snap.prev_day.close else None
            self._cache.update(snap.ticker, price, prev_close=prev_close)

    async def _poll_eod(self) -> None:
        sessions = await asyncio.to_thread(self._recent_closes)
        if not sessions:
            raise EndOfDayDataMissing("no grouped daily bars for recent trading days")
        latest, previous = sessions[0], sessions[-1]
        self._eod_closes = {t: (close, previous.get(t, close)) for t, close in latest.items()}
        for ticker in self._tickers:
            self._write_eod(ticker)

    def _recent_closes(self) -> list[dict[str, float]]:
        """Closes for the two most recent finished trading days, newest first. Runs in a thread.

        Starts at yesterday (New York time) because the free plan only has a day's bars
        after it ends. Weekends are skipped without a call, and at most MAX_EOD_LOOKUPS
        calls are made, so a refresh fits the free plan's 5 calls/min.
        """
        sessions: list[dict[str, float]] = []
        day = us_market_today()
        lookups = 0
        while len(sessions) < 2 and lookups < MAX_EOD_LOOKUPS:
            day -= timedelta(days=1)
            if day.weekday() >= 5:  # Saturday or Sunday
                continue
            lookups += 1
            try:
                aggs = self._client.get_grouped_daily_aggs(day.isoformat())
            except BadResponse as e:
                if is_not_authorized(e):
                    continue  # this day is not available on the plan (yet)
                raise
            closes = {a.ticker: a.close for a in aggs if a.ticker and a.close}
            if closes:  # empty on market holidays
                sessions.append(closes)
        return sessions

    def _write_eod(self, ticker: str) -> None:
        if ticker in self._eod_closes:
            close, prev_close = self._eod_closes[ticker]
            self._cache.update(ticker, close, prev_close=prev_close)

    def _record_success(self) -> None:
        if self._failures:
            logger.info("Massive polling recovered after %d failed attempt(s)", self._failures)
        self._failures = 0
        self._last_success = time.time()
        self._last_error = None

    def _record_failure(self, message: str) -> None:
        self._failures += 1
        self._last_error = message
        logger.error("%s (attempt %d, next try in %.0fs)", message, self._failures, self._next_delay())
