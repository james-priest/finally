from app.services.llm.prompt import SNAPSHOT_HEADER, SYSTEM_PROMPT, build_context, build_messages

PORTFOLIO = {
    "cash_balance": 8100.0,
    "positions_value": 1905.0,
    "total_value": 10005.0,
    "unrealized_pnl": 5.0,
    "positions": [
        {
            "ticker": "AAPL",
            "quantity": 10.0,
            "avg_cost": 190.0,
            "current_price": 190.5,
            "market_value": 1905.0,
            "unrealized_pnl": 5.0,
            "unrealized_pnl_percent": 0.2632,
        }
    ],
}
WATCHLIST = [
    {"ticker": "AAPL", "added_at": "t", "quote": {"price": 190.5, "day_change_percent": -1.25}},
    {"ticker": "PYPL", "added_at": "t", "quote": None},
]
EMPTY = {
    "cash_balance": 10000.0,
    "positions_value": 0.0,
    "total_value": 10000.0,
    "unrealized_pnl": 0.0,
    "positions": [],
}


def test_context_lists_cash_positions_and_watchlist():
    context = build_context(PORTFOLIO, WATCHLIST)
    assert "Cash: $8,100.00" in context
    assert "Total portfolio value: $10,005.00" in context
    assert "- AAPL: 10 shares, avg cost $190.00, price $190.50, value $1,905.00, P&L $5.00 (+0.26%)" in context
    assert "- AAPL: $190.50 (-1.25% today)" in context
    assert "- PYPL: no price yet" in context


def test_context_with_nothing_held_or_watched():
    context = build_context(EMPTY, [])
    assert "Positions:\n- none" in context
    assert "Watchlist:\n- empty" in context


def test_messages_order_and_action_results_in_history():
    actions = {
        "trades": [{"ticker": "AAPL", "status": "failed", "error": "Insufficient cash"}],
        "watchlist_changes": [],
    }
    history = [
        {"role": "user", "content": "buy 1000 AAPL", "actions": None},
        {"role": "assistant", "content": "Buying.", "actions": actions},
        {"role": "assistant", "content": "Hello.", "actions": {"trades": [], "watchlist_changes": []}},
    ]
    messages = build_messages("CTX", history, "why?")

    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[1] == {"role": "user", "content": "buy 1000 AAPL"}
    assert messages[2]["content"].startswith("Buying.\n\n[Action results:")
    assert "Insufficient cash" in messages[2]["content"]
    assert messages[3] == {"role": "assistant", "content": "Hello."}
    # the live snapshot sits after the history so the model doesn't re-apply earlier trades to it
    assert messages[4] == {"role": "system", "content": f"{SNAPSHOT_HEADER}\nCTX"}
    assert messages[5] == {"role": "user", "content": "why?"}
    assert len(messages) == 6
