"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { liveValuation } from "@/lib/portfolio";
import type { Portfolio, Side, Snapshot, WatchlistEntry } from "@/lib/types";
import { usePriceStream } from "@/lib/usePriceStream";
import { ChatPanel } from "./ChatPanel";
import { Header } from "./Header";
import { Heatmap } from "./Heatmap";
import { MainChart } from "./MainChart";
import { PnlChart } from "./PnlChart";
import { PositionsTable } from "./PositionsTable";
import { TradeBar } from "./TradeBar";
import { Watchlist } from "./Watchlist";

const HISTORY_POLL_MS = 30_000;

export function Terminal() {
  const { prices, history, status } = usePriceStream();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistEntry[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [tradeTicker, setTradeTicker] = useState("");

  const refreshHistory = useCallback(
    () => api.getHistory().then((r) => setSnapshots(r.snapshots)),
    [],
  );
  const refreshPortfolio = useCallback(
    () => Promise.all([api.getPortfolio().then(setPortfolio), refreshHistory()]),
    [refreshHistory],
  );
  const refreshWatchlist = useCallback(
    () => api.getWatchlist().then((r) => setWatchlist(r.tickers)),
    [],
  );

  useEffect(() => {
    refreshPortfolio();
    refreshWatchlist();
    const id = setInterval(refreshHistory, HISTORY_POLL_MS);
    return () => clearInterval(id);
  }, [refreshPortfolio, refreshWatchlist, refreshHistory]);

  const live = portfolio && liveValuation(portfolio, prices);
  const chartTicker =
    selected && (prices[selected] || watchlist.some((w) => w.ticker === selected))
      ? selected
      : (watchlist[0]?.ticker ?? null);

  function select(ticker: string) {
    setSelected(ticker);
    setTradeTicker(ticker);
  }

  async function trade(ticker: string, quantity: number, side: Side) {
    const result = await api.trade(ticker, quantity, side);
    setPortfolio(result.portfolio);
    refreshHistory();
    return result.trade;
  }

  async function addTicker(ticker: string) {
    const entry = await api.addTicker(ticker);
    setWatchlist((w) => [...w, entry]);
  }

  async function removeTicker(ticker: string) {
    await api.removeTicker(ticker);
    setWatchlist((w) => w.filter((e) => e.ticker !== ticker));
  }

  return (
    <div className="flex h-full min-h-[640px] flex-col">
      <Header portfolio={live} status={status} />
      <div className="flex min-h-0 flex-1">
        <main className="grid min-h-0 min-w-0 flex-1 grid-cols-[280px_1fr] gap-px bg-line">
          <Watchlist
            entries={watchlist}
            prices={prices}
            history={history}
            selected={chartTicker}
            onSelect={select}
            onAdd={addTicker}
            onRemove={removeTicker}
          />
          <div className="grid min-h-0 min-w-0 grid-rows-[minmax(220px,1.2fr)_auto_minmax(260px,1fr)] gap-px">
            <MainChart
              ticker={chartTicker}
              quote={chartTicker ? prices[chartTicker] : undefined}
              points={chartTicker ? (history[chartTicker] ?? []) : []}
            />
            <TradeBar ticker={tradeTicker} onTickerChange={setTradeTicker} onTrade={trade} />
            <div className="grid min-h-0 grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] gap-px">
              <PositionsTable positions={live?.positions ?? []} onSelect={select} />
              <div className="grid min-h-0 grid-rows-2 gap-px">
                <Heatmap positions={live?.positions ?? []} />
                <PnlChart snapshots={snapshots} />
              </div>
            </div>
          </div>
        </main>
        <ChatPanel
          onActions={() => {
            refreshPortfolio();
            refreshWatchlist();
          }}
        />
      </div>
    </div>
  );
}
