import pytest

from app.services.market import PriceCache, create_market_data_source, normalize_ticker
from app.services.market.massive import MassiveDataSource
from app.services.market.simulator import SimulatorDataSource


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("aapl", "AAPL"), (" brk.b ", "BRK.B"), ("V", "V"), ("bf-b", "BF-B"), ("GOOGL", "GOOGL")],
)
def test_normalize_ticker_accepts_symbols(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "1ABC", "AA PL", "$AAPL", "TOOLONGTICKER", "AAPL."])
def test_normalize_ticker_rejects_garbage(raw):
    with pytest.raises(ValueError):
        normalize_ticker(raw)


def test_factory_selects_source(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)
    monkeypatch.setenv("MASSIVE_API_KEY", "   ")
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)
    monkeypatch.setenv("MASSIVE_API_KEY", "abc")
    assert isinstance(create_market_data_source(PriceCache()), MassiveDataSource)


@pytest.mark.parametrize(("raw", "expected"), [("", 15.0), ("5", 5.0), ("0.2", 15.0), ("fast", 15.0)])
def test_factory_poll_seconds(monkeypatch, raw, expected):
    monkeypatch.setenv("MASSIVE_API_KEY", "abc")
    monkeypatch.setenv("MASSIVE_POLL_SECONDS", raw)
    assert create_market_data_source(PriceCache())._poll_seconds == expected


async def test_sync_tickers_adds_missing_and_removes_extra():
    cache = PriceCache()
    source = SimulatorDataSource(cache)
    await source.start(["AAPL", "MSFT"])
    await source.sync_tickers(["MSFT", "PYPL"])
    assert source.get_tickers() == ["MSFT", "PYPL"]
    assert cache.get("AAPL") is None
    assert cache.get_price("PYPL") is not None
    await source.stop()
