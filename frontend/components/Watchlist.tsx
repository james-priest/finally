"use client";

import { useState, type FormEvent } from "react";
import { signedPercent, trendClass } from "@/lib/format";
import type { PriceMap, WatchlistEntry } from "@/lib/types";
import type { PriceHistory } from "@/lib/usePriceStream";
import { Panel } from "./Panel";
import { PriceCell } from "./PriceCell";
import { Sparkline } from "./Sparkline";

interface WatchlistProps {
  entries: WatchlistEntry[];
  prices: PriceMap;
  history: PriceHistory;
  selected: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => Promise<void>;
  onRemove: (ticker: string) => Promise<void>;
}

export function Watchlist({
  entries,
  prices,
  history,
  selected,
  onSelect,
  onAdd,
  onRemove,
}: WatchlistProps) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ticker = input.trim().toUpperCase();
    if (!ticker) return;
    try {
      await onAdd(ticker);
      setInput("");
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <Panel title="Watchlist" testId="watchlist" aside={<span className="text-xs text-ink-3">{entries.length}</span>}>
      <div className="flex h-full flex-col">
        <ul className="min-h-0 flex-1 overflow-y-auto">
          {entries.map((entry) => {
            const quote = prices[entry.ticker] ?? entry.quote;
            const isSelected = entry.ticker === selected;
            return (
              <li
                key={entry.ticker}
                data-testid={`watchlist-row-${entry.ticker}`}
                onClick={() => onSelect(entry.ticker)}
                className={`group grid cursor-pointer grid-cols-[52px_1fr_auto_24px] items-center gap-x-2 border-b border-l-2 border-b-line/60 py-1 pr-1.5 pl-2.5 hover:bg-raised ${
                  isSelected ? "border-l-accent bg-raised" : "border-l-transparent"
                }`}
              >
                <button
                  type="button"
                  className="text-left font-mono text-[13px] font-medium text-ink"
                  aria-pressed={isSelected}
                >
                  {entry.ticker}
                </button>
                <Sparkline
                  points={history[entry.ticker] ?? []}
                  up={quote ? quote.day_change_percent >= 0 : true}
                />
                <div className="flex flex-col items-end leading-tight">
                  <span className="text-sm">
                    {quote ? (
                      <PriceCell price={quote.price} testId={`watchlist-price-${entry.ticker}`} />
                    ) : (
                      <span data-testid={`watchlist-price-${entry.ticker}`} className="px-1 text-ink-3">
                        --
                      </span>
                    )}
                  </span>
                  <span className={`px-1 text-[11px] ${quote ? trendClass(quote.day_change_percent) : "text-ink-3"}`}>
                    {quote ? signedPercent(quote.day_change_percent) : ""}
                  </span>
                </div>
                <button
                  type="button"
                  data-testid={`watchlist-remove-${entry.ticker}`}
                  aria-label={`Remove ${entry.ticker} from watchlist`}
                  onClick={(e) => {
                    e.stopPropagation();
                    void onRemove(entry.ticker);
                  }}
                  className="h-6 w-6 rounded text-ink-3 opacity-40 group-hover:opacity-100 hover:bg-line hover:text-ink focus-visible:opacity-100"
                >
                  &times;
                </button>
              </li>
            );
          })}
        </ul>
        <form onSubmit={submit} className="shrink-0 border-t border-line p-2">
          <div className="flex gap-1.5">
            <input
              data-testid="watchlist-add-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Add ticker"
              aria-label="Ticker to add"
              className="min-w-0 flex-1 rounded border border-line bg-page px-2 py-1 font-mono text-[13px] uppercase placeholder:font-sans placeholder:normal-case placeholder:text-ink-3"
            />
            <button
              type="submit"
              data-testid="watchlist-add-button"
              className="rounded bg-submit px-3 py-1 text-[13px] font-medium text-white hover:bg-submit-hover"
            >
              Add
            </button>
          </div>
          {error && <p className="mt-1.5 text-xs text-down">{error}</p>}
        </form>
      </div>
    </Panel>
  );
}
