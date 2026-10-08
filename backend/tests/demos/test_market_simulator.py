import io

import pytest
from rich.console import Console

from app.services.market import PriceCache
from demos.market_simulator import Dashboard, parse_args, run, sparkline


def plain_console() -> Console:
    return Console(file=io.StringIO(), record=True, width=150, color_system=None)


def render_text(dashboard: Dashboard, now: float) -> str:
    console = plain_console()
    console.print(dashboard.render(now))
    return console.export_text()


def test_sparkline_scales_to_its_own_range():
    assert sparkline([1, 2, 3, 4, 5, 6, 7, 8]) == "▁▂▃▄▅▆▇█"
    assert sparkline([5.0, 5.0, 5.0]) == "▄▄▄"
    assert sparkline([]) == ""
    line = sparkline(range(100), width=10)  # only the last 10 values
    assert (len(line), line[0], line[-1]) == (10, "▁", "█")


def test_dashboard_tracks_prices_and_logs_jump_events():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("PYPL", 60.0)
    dashboard = Dashboard(seed=1, tick_seconds=0.5, time_scale=20, jumps=0.0005)
    dashboard.ingest(cache.all(), now=1000.0)
    cache.update("AAPL", 190.1)  # an ordinary tick
    cache.update("PYPL", 62.4)  # +4% in one tick: a jump
    dashboard.ingest(cache.all(), now=1000.5)

    assert [(e.ticker, round(e.move, 4)) for e in dashboard.events] == [("PYPL", 0.04)]
    assert (dashboard.quotes["PYPL"].high, dashboard.quotes["PYPL"].low) == (62.4, 60.0)
    text = render_text(dashboard, now=1001.0)
    assert "AAPL" in text and "PYPL ⚡" in text  # the jump is highlighted for a few seconds
    assert "⚡ +4.00%" in text  # in the event log
    assert "other" in text  # tickers without a profile are grouped as "other"
    assert "PYPL ⚡" not in render_text(dashboard, now=1010.0)  # the highlight fades

    cache.remove("PYPL")
    dashboard.ingest(cache.all(), now=1011.0)
    assert list(dashboard.quotes) == ["AAPL"]  # removed tickers drop out, as in an SSE event


async def test_run_drives_the_real_simulator():
    args = parse_args(["--tickers", "aapl,MSFT,aapl", "--seed", "7", "--tick", "0.01", "--duration", "0.3"])
    console = plain_console()
    dashboard = await run(args, console)
    assert list(dashboard.quotes) == ["AAPL", "MSFT"]  # normalized, duplicates dropped
    assert dashboard.frames > 5
    output = console.export_text()
    assert "MSFT" in output and "Stopped after" in output


@pytest.mark.parametrize(
    "argv", [["--tickers", "NOT A TICKER"], ["--tickers", " , "], ["--tick", "0"], ["--jumps", "1.5"]]
)
def test_parse_args_rejects_bad_input(argv, capsys):
    with pytest.raises(SystemExit):
        parse_args(argv)
    assert "error" in capsys.readouterr().err
