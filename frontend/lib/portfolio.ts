import type { Portfolio, PriceMap } from "./types";

/** Revalue a portfolio from the server with the latest streamed prices. */
export function liveValuation(portfolio: Portfolio, prices: PriceMap): Portfolio {
  const positions = portfolio.positions.map((p) => {
    const price = prices[p.ticker]?.price ?? p.current_price;
    const cost = p.avg_cost * p.quantity;
    const marketValue = price * p.quantity;
    const pnl = marketValue - cost;
    return {
      ...p,
      current_price: price,
      market_value: marketValue,
      unrealized_pnl: pnl,
      unrealized_pnl_percent: cost > 0 ? (pnl / cost) * 100 : 0,
    };
  });
  const positionsValue = positions.reduce((sum, p) => sum + p.market_value, 0);
  return {
    cash_balance: portfolio.cash_balance,
    positions_value: positionsValue,
    total_value: portfolio.cash_balance + positionsValue,
    unrealized_pnl: positions.reduce((sum, p) => sum + p.unrealized_pnl, 0),
    positions,
  };
}
