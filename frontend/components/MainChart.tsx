"use client";

import { money, signedPercent, trendClass } from "@/lib/format";
import type { PriceUpdate } from "@/lib/types";
import type { PricePoint } from "@/lib/usePriceStream";
import { Panel } from "./Panel";
import { TimeSeriesChart } from "./TimeSeriesChart";

interface MainChartProps {
  ticker: string | null;
  quote: PriceUpdate | undefined;
  points: PricePoint[];
}

export function MainChart({ ticker, quote, points }: MainChartProps) {
  const title = ticker ? (
    <span className="flex items-baseline gap-3">
      <span className="font-mono text-sm font-medium text-ink">{ticker}</span>
      {quote && (
        <>
          <span className="text-sm text-ink">{money(quote.price)}</span>
          <span className={`text-xs ${trendClass(quote.day_change_percent)}`}>
            {signedPercent(quote.day_change_percent)} today
          </span>
        </>
      )}
    </span>
  ) : (
    "Chart"
  );

  return (
    <Panel title={title} aside={<span className="text-xs text-ink-3">Since page load</span>}>
      <div data-testid="main-chart" data-ticker={ticker ?? ""} className="absolute inset-0 p-1">
        {ticker ? (
          <TimeSeriesChart points={points} color="#209dd7" />
        ) : (
          <p className="p-3 text-sm text-ink-3">Select a ticker in the watchlist to chart it.</p>
        )}
      </div>
    </Panel>
  );
}
