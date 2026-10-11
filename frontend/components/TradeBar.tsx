"use client";

import { useState } from "react";
import { money, quantity as fmtQuantity } from "@/lib/format";
import type { Side, Trade } from "@/lib/types";

interface TradeBarProps {
  ticker: string;
  onTickerChange: (ticker: string) => void;
  onTrade: (ticker: string, quantity: number, side: Side) => Promise<Trade>;
}

export function TradeBar({ ticker, onTickerChange, onTrade }: TradeBarProps) {
  const [qty, setQty] = useState("1");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filled, setFilled] = useState<string | null>(null);

  async function submit(side: Side) {
    const symbol = ticker.trim().toUpperCase();
    const amount = Number(qty);
    if (!symbol) return setError("Enter a ticker.");
    if (!(amount > 0)) return setError("Enter a quantity greater than 0.");
    setPending(true);
    setError(null);
    setFilled(null);
    try {
      const trade = await onTrade(symbol, amount, side);
      setFilled(
        `${trade.side === "buy" ? "Bought" : "Sold"} ${fmtQuantity(trade.quantity)} ${trade.ticker} at ${money(trade.price)}`,
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit("buy");
      }}
      className="flex flex-wrap items-center gap-2 bg-panel px-3 py-2"
    >
      <span className="text-[13px] font-medium text-ink-2">Trade</span>
      <input
        data-testid="trade-ticker-input"
        value={ticker}
        onChange={(e) => onTickerChange(e.target.value.toUpperCase())}
        placeholder="Ticker"
        aria-label="Ticker"
        className="w-24 rounded border border-line bg-page px-2 py-1 font-mono text-[13px] uppercase placeholder:font-sans placeholder:normal-case placeholder:text-ink-3"
      />
      <input
        data-testid="trade-quantity-input"
        value={qty}
        onChange={(e) => setQty(e.target.value)}
        type="number"
        min="0"
        step="any"
        aria-label="Quantity"
        placeholder="Qty"
        className="w-24 rounded border border-line bg-page px-2 py-1 text-[13px] placeholder:text-ink-3"
      />
      <button
        type="submit"
        data-testid="trade-buy-button"
        disabled={pending}
        className="rounded bg-submit px-4 py-1 text-[13px] font-medium text-white hover:bg-submit-hover disabled:opacity-50"
      >
        Buy
      </button>
      <button
        type="button"
        data-testid="trade-sell-button"
        disabled={pending}
        onClick={() => void submit("sell")}
        className="rounded border border-submit px-4 py-1 text-[13px] font-medium text-ink hover:bg-submit/25 disabled:opacity-50"
      >
        Sell
      </button>
      <span className="text-xs text-ink-3">Market order, fills at the last price</span>
      {error && (
        <p data-testid="trade-error" role="alert" className="text-[13px] text-down">
          {error}
        </p>
      )}
      {filled && <p className="text-[13px] text-ink-2">{filled}</p>}
    </form>
  );
}
