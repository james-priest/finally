import logging
import os

from .base import MarketDataSource
from .cache import PriceCache
from .massive import MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 15.0


def create_market_data_source(cache: PriceCache) -> MarketDataSource:
    """Massive if MASSIVE_API_KEY is set and non-empty, otherwise the simulator."""
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not api_key:
        logger.info("Market data: built-in simulator")
        return SimulatorDataSource(cache)
    poll_seconds = _poll_seconds()
    logger.info("Market data: Massive API, polling every %.0fs", poll_seconds)
    return MassiveDataSource(cache, api_key, poll_seconds=poll_seconds)


def _poll_seconds() -> float:
    raw = os.environ.get("MASSIVE_POLL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_POLL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if not value >= 1:  # also rejects nan
        logger.warning("Ignoring MASSIVE_POLL_SECONDS=%r (need a number >= 1)", raw)
        return DEFAULT_POLL_SECONDS
    return value
