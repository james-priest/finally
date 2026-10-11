"""Chat orchestration: context, LLM call, auto-execution of its actions, persistence."""

import asyncio
import logging

import db
from app.services import portfolio, watchlist
from app.services.llm.client import call_llm
from app.services.llm.prompt import build_context, build_messages
from app.services.llm.schema import LLMReply, TradeInstruction, WatchlistInstruction
from app.services.market import MarketDataSource, PriceCache

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 20
FALLBACK_MESSAGE = "Sorry, I couldn't process that request right now. Please try again."


async def handle_chat(user_message: str, source: MarketDataSource, cache: PriceCache) -> dict:
    """Answer one user message and return the stored assistant message (TEAM_CONTRACT.md §3)."""
    history = await asyncio.to_thread(db.list_chat_messages, HISTORY_LIMIT)
    context = build_context(portfolio.get_portfolio(cache), watchlist.list_watchlist(cache))
    await asyncio.to_thread(db.insert_chat_message, "user", user_message)
    try:
        reply = await call_llm(build_messages(context, history, user_message))
    except Exception:  # network, provider or malformed output: the user gets an apology, never a 500
        logger.exception("LLM call failed")
        reply = LLMReply(message=FALLBACK_MESSAGE)
    actions = {
        "trades": [await _run_trade(t, source, cache) for t in reply.trades],
        "watchlist_changes": [await _run_watchlist_change(c, source, cache) for c in reply.watchlist_changes],
    }
    return await asyncio.to_thread(db.insert_chat_message, "assistant", reply.message, actions)


async def _run_trade(t: TradeInstruction, source: MarketDataSource, cache: PriceCache) -> dict:
    result = {"ticker": t.ticker.strip().upper(), "side": t.side, "quantity": t.quantity}
    try:
        trade = await portfolio.execute_trade(t.ticker, t.side, t.quantity, source, cache)
    except portfolio.TradeError as e:
        return {**result, "status": "failed", "price": None, "error": str(e)}
    return {**result, "ticker": trade["ticker"], "status": "executed", "price": trade["price"], "error": None}


async def _run_watchlist_change(c: WatchlistInstruction, source: MarketDataSource, cache: PriceCache) -> dict:
    result = {"ticker": c.ticker.strip().upper(), "action": c.action}
    try:
        if c.action == "add":
            await watchlist.add_ticker(c.ticker, source, cache)
        else:
            await watchlist.remove_ticker(c.ticker, source)
    except watchlist.WatchlistError as e:
        return {**result, "status": "failed", "error": str(e)}
    return {**result, "status": "executed", "error": None}


async def list_chat() -> list[dict]:
    return await asyncio.to_thread(db.list_chat_messages)
