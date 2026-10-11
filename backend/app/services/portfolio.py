"""Portfolio: trade execution and valuation. Shared by the REST routes and the chat flow.

The DB calls are small SQLite queries run directly on the event loop. That keeps a trade's
read-validate-write free of awaits, so two trades (REST and chat) can never interleave.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

import db
from app.services.market import MarketDataSource, PriceCache, normalize_ticker

logger = logging.getLogger(__name__)

Side = Literal["buy", "sell"]

EPSILON = 1e-9  # float slack for fractional shares and cents
SNAPSHOT_SECONDS = 30.0


class TradeError(Exception):
    """A trade failed validation: bad input, insufficient cash or shares, or no price."""


@dataclass(frozen=True, slots=True)
class Holding:
    quantity: float
    avg_cost: float


def apply_trade(
    side: Side, quantity: float, price: float, cash: float, holding: Holding | None
) -> tuple[float, Holding | None]:
    """Return the new cash balance and holding after a fill. A holding of None means no position."""
    if quantity <= 0:
        raise TradeError("Quantity must be greater than zero")
    cost = quantity * price
    if side == "buy":
        if cost > cash + EPSILON:
            raise TradeError(f"Insufficient cash: need ${cost:,.2f}, have ${cash:,.2f}")
        held = holding.quantity if holding else 0.0
        total_cost = (holding.quantity * holding.avg_cost if holding else 0.0) + cost
        new_quantity = held + quantity
        return cash - cost, Holding(new_quantity, total_cost / new_quantity)
    held = holding.quantity if holding else 0.0
    if holding is None or quantity > held + EPSILON:
        raise TradeError(f"Insufficient shares: trying to sell {quantity:g}, own {held:g}")
    remaining = held - quantity
    return cash + cost, Holding(remaining, holding.avg_cost) if remaining > EPSILON else None


def value_portfolio(cash: float, holdings: dict[str, Holding], cache: PriceCache) -> dict:
    """The GET /api/portfolio shape. A position with no live price is valued at its average cost."""
    positions = []
    positions_value = total_pnl = 0.0
    for ticker in sorted(holdings):
        h = holdings[ticker]
        live = cache.get_price(ticker)
        price = live if live is not None else h.avg_cost
        cost_basis = h.quantity * h.avg_cost
        market_value = h.quantity * price
        pnl = market_value - cost_basis
        positions_value += market_value
        total_pnl += pnl
        positions.append(
            {
                "ticker": ticker,
                "quantity": h.quantity,
                "avg_cost": round(h.avg_cost, 4),
                "current_price": price,
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_percent": round(pnl / cost_basis * 100, 4) if cost_basis else 0.0,
            }
        )
    return {
        "cash_balance": round(cash, 2),
        "positions_value": round(positions_value, 2),
        "total_value": round(cash + positions_value, 2),
        "unrealized_pnl": round(total_pnl, 2),
        "positions": positions,
    }


def get_portfolio(cache: PriceCache) -> dict:
    holdings = {p["ticker"]: Holding(p["quantity"], p["avg_cost"]) for p in db.get_positions()}
    return value_portfolio(db.get_cash(), holdings, cache)


async def execute_trade(ticker: str, side: Side, quantity: float, source: MarketDataSource, cache: PriceCache) -> dict:
    """Fill a market order at the current price and return the trade. Raises TradeError if it can't fill.

    The ticker is normalized here too, so the chat flow can pass the LLM's raw symbol.
    """
    try:
        ticker = normalize_ticker(ticker)
    except ValueError as e:
        raise TradeError(str(e)) from e
    if side not in ("buy", "sell"):
        raise TradeError(f"Side must be 'buy' or 'sell', not {side!r}")
    await source.add_ticker(ticker)  # no-op if tracked; otherwise start tracking and price it now
    try:
        price = cache.get_price(ticker)
        if price is None:
            raise TradeError(f"No price available for {ticker}")
        row = db.get_position(ticker)
        holding = Holding(row["quantity"], row["avg_cost"]) if row else None
        cash, holding = apply_trade(side, quantity, price, db.get_cash(), holding)
        trade = db.record_trade(
            ticker, side, quantity, price, cash, (holding.quantity, holding.avg_cost) if holding else None
        )
        record_snapshot(cache)
        return trade
    finally:
        await source.sync_tickers(db.tracked_tickers())  # stop tracking it if no position resulted


def get_history() -> list[dict]:
    return db.list_snapshots()


def record_snapshot(cache: PriceCache) -> dict:
    return db.insert_snapshot(get_portfolio(cache)["total_value"])


async def run_snapshots(cache: PriceCache, interval: float = SNAPSHOT_SECONDS) -> None:
    """Record a snapshot now, then every `interval` seconds until cancelled. Never dies on an error."""
    while True:
        try:
            record_snapshot(cache)
        except Exception:
            logger.exception("Portfolio snapshot failed")
        await asyncio.sleep(interval)
