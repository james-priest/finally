"""System prompt, portfolio context and message list for the chat LLM call."""

import json

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant in a simulated trading workstation. The money is virtual.

You can:
- Analyze the user's portfolio: composition, risk concentration, and unrealized P&L.
- Suggest trades with brief reasoning.
- Execute market orders when the user asks or agrees, by listing them in "trades". They fill instantly
  at the current price.
- Manage the watchlist proactively, by listing changes in "watchlist_changes".

Rules:
- Be concise and data-driven. Use the numbers in the portfolio context.
- Only trade when the user asked for it or agreed to it. Buys need enough cash; sells need enough shares.
- Use plain ticker symbols such as AAPL. Quantities are share counts greater than zero; fractions are allowed.
- Earlier assistant turns list the outcome of their actions. If an action failed, tell the user why.
- The latest portfolio snapshot comes right before the user's newest message. It is live and already includes
  every trade above: use its numbers as they are and never add past trades to them.
- Always respond with JSON matching the schema: "message" (your reply to the user), "trades" and "watchlist_changes" \
(empty lists when there is nothing to do)."""

SNAPSHOT_HEADER = "Portfolio snapshot, live as of now (after everything above):"


def build_context(portfolio: dict, watchlist: list[dict]) -> str:
    """The live portfolio snapshot shown to the model.

    `portfolio` is the GET /api/portfolio shape; `watchlist` is the GET /api/watchlist entries
    ({ticker, added_at, quote}, quote None when there is no price yet).
    """
    lines = [
        f"Cash: ${portfolio['cash_balance']:,.2f}",
        f"Positions value: ${portfolio['positions_value']:,.2f}",
        f"Total portfolio value: ${portfolio['total_value']:,.2f}",
        f"Unrealized P&L: ${portfolio['unrealized_pnl']:,.2f}",
        "Positions:",
    ]
    for p in portfolio["positions"]:
        lines.append(
            f"- {p['ticker']}: {p['quantity']:g} shares, avg cost ${p['avg_cost']:,.2f}, "
            f"price ${p['current_price']:,.2f}, value ${p['market_value']:,.2f}, "
            f"P&L ${p['unrealized_pnl']:,.2f} ({p['unrealized_pnl_percent']:+.2f}%)"
        )
    if not portfolio["positions"]:
        lines.append("- none")
    lines.append("Watchlist:")
    for w in watchlist:
        q = w["quote"]
        if q is None:
            lines.append(f"- {w['ticker']}: no price yet")
        else:
            lines.append(f"- {w['ticker']}: ${q['price']:,.2f} ({q['day_change_percent']:+.2f}% today)")
    if not watchlist:
        lines.append("- empty")
    return "\n".join(lines)


def build_messages(context: str, history: list[dict], user_message: str) -> list[dict]:
    """System prompt, earlier turns (stored chat messages), the live snapshot, then the new user message.

    The snapshot goes last: placed before the history, the model read it as the starting state and
    re-applied earlier trades on top of it.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        content = m["content"]
        if m["role"] == "assistant" and m["actions"] and (m["actions"]["trades"] or m["actions"]["watchlist_changes"]):
            content += f"\n\n[Action results: {json.dumps(m['actions'])}]"
        messages.append({"role": m["role"], "content": content})
    messages.append({"role": "system", "content": f"{SNAPSHOT_HEADER}\n{context}"})
    messages.append({"role": "user", "content": user_message})
    return messages
