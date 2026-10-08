"""Live terminal dashboard for the market data simulator.

Runs the real SimulatorDataSource and PriceCache, and redraws whenever the cache changes,
the same way the SSE stream pushes to the browser.

    cd backend
    uv run python -m demos.market_simulator                          # Ctrl+C to quit
    uv run python -m demos.market_simulator --seed 42 --duration 60
    uv run python -m demos.market_simulator --tickers AAPL,NVDA,PYPL --jumps 0.005
"""

import argparse
import asyncio
import math
import random
import time
from collections import deque
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.services.market import PriceCache, PriceUpdate, normalize_ticker
from app.services.market.simulator import PROFILES, GBMSimulator, SimulatorDataSource, profile_for

SPARK_CHARS = "▁▂▃▄▅▆▇█"
HISTORY = 40  # ticks kept per ticker for the sparkline
JUMP_THRESHOLD = 0.015  # a one-tick log move this large is a jump event; diffusion alone stays under 0.5%
JUMP_HIGHLIGHT_SECONDS = 3.0
MAX_EVENTS = 8
UP, DOWN, FLAT = "green", "red", "grey50"


def sparkline(values: Sequence[float], width: int = HISTORY) -> str:
    """Block-character sparkline of the last `width` values, scaled to their own range."""
    values = list(values)[-width:]
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        return "▄" * len(values)
    scale = (len(SPARK_CHARS) - 1) / (hi - lo)
    return "".join(SPARK_CHARS[round((v - lo) * scale)] for v in values)


def color_for(value: float) -> str:
    return UP if value > 0 else DOWN if value < 0 else FLAT


def sector_of(ticker: str) -> str:
    """The simulator's sector, or "other" for tickers without a profile (each is its own sector)."""
    return profile_for(ticker).sector if ticker in PROFILES else "other"


def format_price(price: float) -> str:
    return f"{price:,.2f}" if price >= 1 else f"{price:.4f}"


@dataclass
class Quote:
    sector: str
    history: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY))
    high: float = 0.0
    low: float = math.inf
    tick_move: float = 0.0  # change since the previous frame
    jumped_at: float | None = None


@dataclass(frozen=True)
class Event:
    at: float
    ticker: str
    move: float  # fractional, e.g. 0.034 for +3.4%


class Dashboard:
    """Turns successive cache snapshots into a rich renderable. No I/O, so it is easy to test."""

    def __init__(self, *, seed: int | None, tick_seconds: float, time_scale: float, jumps: float) -> None:
        self.latest: dict[str, PriceUpdate] = {}
        self.quotes: dict[str, Quote] = {}
        self.events: deque[Event] = deque(maxlen=MAX_EVENTS)
        self.frames = 0
        self.jumps_seen = 0
        self.started = time.time()
        self.settings = (
            f"seed {'random' if seed is None else seed} · tick {tick_seconds:g}s · "
            f"time scale {time_scale:g}x · jump p={jumps:g}"
        )

    def ingest(self, prices: dict[str, PriceUpdate], now: float | None = None) -> None:
        """Take one cache snapshot: extend histories, note each tick's move, and log jump events."""
        now = time.time() if now is None else now
        self.frames += 1
        self.latest = prices
        for ticker in self.quotes.keys() - prices.keys():
            del self.quotes[ticker]  # removed from the cache, as it would drop out of an SSE event
        for ticker, update in prices.items():
            quote = self.quotes.setdefault(ticker, Quote(sector=sector_of(ticker)))
            last = quote.history[-1] if quote.history else update.price
            quote.tick_move = update.price - last
            if abs(math.log(update.price / last)) > JUMP_THRESHOLD:
                quote.jumped_at = now
                self.jumps_seen += 1
                self.events.appendleft(Event(now, ticker, update.price / last - 1))
            quote.history.append(update.price)
            quote.high = max(quote.high, update.price)
            quote.low = min(quote.low, update.price)

    def render(self, now: float | None = None) -> RenderableType:
        now = time.time() if now is None else now
        body = Table.grid(expand=True, padding=(0, 1))
        body.add_column(ratio=3)
        body.add_column(ratio=2)
        body.add_row(self._prices(now), Group(self._sectors(), self._events()))
        footer = Text(
            "SimulatorDataSource → PriceCache → this view, redrawn on every cache change like the SSE stream. "
            "Ctrl+C to quit.",
            style="grey50",
        )
        return Group(self._header(now), body, footer)

    def _header(self, now: float) -> Panel:
        elapsed = max(now - self.started, 0.0)
        minutes, seconds = divmod(int(elapsed), 60)
        rate = self.frames / elapsed if elapsed > 0 else 0.0
        days = [u.day_change_percent for u in self.latest.values()]
        line = Text.assemble(
            ("● LIVE", "bold green"),
            f"   {len(self.latest)} tickers   {self.frames:,} ticks ({rate:.1f}/s)   ",
            f"up {minutes:02d}:{seconds:02d}   ",
            (f"⚡ {self.jumps_seen} jump{'' if self.jumps_seen == 1 else 's'}", "yellow"),
            "   breadth ",
            (f"▲ {sum(d > 0 for d in days)}", UP),
            " ",
            (f"▼ {sum(d < 0 for d in days)}", DOWN),
        )
        return Panel(
            line,
            title="[bold #ecad0a]FinAlly[/] · Market Simulator",
            subtitle=Text(self.settings, style="grey50"),
            border_style="#209dd7",
        )

    def _prices(self, now: float) -> Panel:
        table = Table(expand=True, box=None, header_style="bold #209dd7", pad_edge=False)
        table.add_column("Ticker", no_wrap=True)
        table.add_column("Sector", style="grey50", no_wrap=True)
        table.add_column("Price", justify="right", no_wrap=True)
        table.add_column("Tick", justify="right", no_wrap=True)
        table.add_column("Day", justify="right", no_wrap=True)
        table.add_column("Trend", no_wrap=True)
        table.add_column("High", justify="right", style="grey62", no_wrap=True)
        table.add_column("Low", justify="right", style="grey62", no_wrap=True)
        for ticker, update in self.latest.items():
            quote = self.quotes[ticker]
            jumping = quote.jumped_at is not None and now - quote.jumped_at < JUMP_HIGHLIGHT_SECONDS
            arrow = "▲" if quote.tick_move > 0 else "▼" if quote.tick_move < 0 else " "
            trend = color_for(quote.history[-1] - quote.history[0])
            table.add_row(
                Text.assemble((ticker, "bold"), (" ⚡", "yellow") if jumping else ""),
                quote.sector,
                Text(
                    f"{format_price(update.price)} {arrow}",
                    style="bold black on yellow" if jumping else f"bold {color_for(quote.tick_move)}",
                ),
                Text(f"{quote.tick_move:+.2f}", style=color_for(quote.tick_move)),
                Text(f"{update.day_change_percent:+.2f}%", style=color_for(update.day_change_percent)),
                Text(sparkline(quote.history), style=trend),
                format_price(quote.high),
                format_price(quote.low),
            )
        return Panel(table, title="Prices", border_style="grey35")

    def _sectors(self) -> Panel:
        by_sector: dict[str, list[float]] = {}
        for ticker, update in self.latest.items():
            by_sector.setdefault(self.quotes[ticker].sector, []).append(update.day_change_percent)
        averages = {sector: sum(days) / len(days) for sector, days in by_sector.items()}
        widest = max((abs(a) for a in averages.values()), default=0.0) or 1.0
        table = Table(expand=True, box=None, show_header=False, pad_edge=False)
        table.add_column("Sector", no_wrap=True)
        table.add_column("n", justify="right", style="grey50")
        table.add_column("Day", justify="right", no_wrap=True)
        table.add_column("Bar", no_wrap=True)
        for sector, average in sorted(averages.items(), key=lambda item: -item[1]):
            bar = "█" * max(1, round(abs(average) / widest * 12)) if average else ""
            table.add_row(
                sector,
                str(len(by_sector[sector])),
                Text(f"{average:+.2f}%", style=color_for(average)),
                Text(bar, style=color_for(average)),
            )
        return Panel(table, title="Sectors (avg day change)", border_style="grey35")

    def _events(self) -> Panel:
        if not self.events:
            body: RenderableType = Text(
                "No jumps yet. With 10 tickers expect about one every 100s; try --jumps 0.005.",
                style="grey50",
            )
        else:
            table = Table(expand=True, box=None, show_header=False, pad_edge=False)
            for event in self.events:
                table.add_row(
                    Text(time.strftime("%H:%M:%S", time.localtime(event.at)), style="grey50"),
                    Text(event.ticker, style="bold"),
                    Text(f"⚡ {event.move:+.2%}", style=color_for(event.move)),
                )
            body = table
        return Panel(body, title="Jump events", border_style="grey35")


async def run(args: argparse.Namespace, console: Console | None = None) -> Dashboard:
    """Run the simulator and the live view until `args.duration` passes (or forever)."""
    console = console or Console()
    cache = PriceCache()
    rng = random.Random(args.seed) if args.seed is not None else None
    simulator = GBMSimulator(tick_seconds=args.tick, time_scale=args.time_scale, event_probability=args.jumps, rng=rng)
    source = SimulatorDataSource(cache, tick_seconds=args.tick, simulator=simulator)
    dashboard = Dashboard(seed=args.seed, tick_seconds=args.tick, time_scale=args.time_scale, jumps=args.jumps)
    deadline = None if args.duration is None else time.monotonic() + args.duration
    await source.start(args.tickers)
    try:
        with Live(dashboard.render(), console=console, auto_refresh=False) as live:
            version = -1  # never equal to cache.version, so the seeded prices show at once
            while True:
                timeout = None if deadline is None else max(deadline - time.monotonic(), 0.0)
                try:
                    version = await asyncio.wait_for(cache.wait_for_change(version), timeout)
                except TimeoutError:
                    break
                dashboard.ingest(cache.all())
                live.update(dashboard.render(), refresh=True)
    finally:
        await source.stop()
        if not console.is_terminal:
            console.line()  # Live leaves its last frame without a newline when output is not a terminal
        console.print(
            f"Stopped after {dashboard.frames:,} ticks and {dashboard.jumps_seen} jump events.",
            style="grey50",
            highlight=False,
        )
    return dashboard


def _tickers(raw: str) -> list[str]:
    try:
        tickers = [normalize_ticker(t) for t in raw.split(",") if t.strip()]
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e
    if not tickers:
        raise argparse.ArgumentTypeError("give at least one ticker")
    return list(dict.fromkeys(tickers))  # drop duplicates, keep order


def _positive(raw: str) -> float:
    value = float(raw)
    if not value > 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {raw}")
    return value


def _probability(raw: str) -> float:
    value = float(raw)
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError(f"must be between 0 and 1, got {raw}")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m demos.market_simulator",
        description="Live terminal dashboard for FinAlly's market data simulator.",
    )
    parser.add_argument(
        "--tickers",
        type=_tickers,
        default=list(PROFILES),
        help="comma-separated symbols (default: the 10 profiled tickers; others get generated profiles)",
    )
    parser.add_argument("--seed", type=int, help="random seed for a reproducible run")
    parser.add_argument("--duration", type=_positive, help="seconds to run (default: until Ctrl+C)")
    parser.add_argument("--tick", type=_positive, default=0.5, help="seconds between ticks (default: 0.5)")
    parser.add_argument(
        "--time-scale", type=_positive, default=20.0, help="trading seconds per real second (default: 20)"
    )
    parser.add_argument(
        "--jumps", type=_probability, default=0.0005, help="jump chance per ticker per tick (default: 0.0005)"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    with suppress(KeyboardInterrupt):  # Ctrl+C: run() has already stopped the source
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
