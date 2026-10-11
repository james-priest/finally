import { describe, expect, it } from "vitest";
import { money, signedMoney, signedPercent } from "./format";
import { liveValuation } from "./portfolio";
import { treemap } from "./treemap";
import { appendPoint, mergeHistory } from "./usePriceStream";
import type { Portfolio, PriceUpdate } from "./types";

function quote(ticker: string, price: number, timestamp = 1000): PriceUpdate {
  return {
    ticker,
    price,
    previous_price: price,
    prev_close: price,
    change: 0,
    day_change_percent: 0,
    direction: "flat",
    timestamp,
  };
}

const portfolio: Portfolio = {
  cash_balance: 8100,
  positions_value: 1900,
  total_value: 10000,
  unrealized_pnl: 0,
  positions: [
    {
      ticker: "AAPL",
      quantity: 10,
      avg_cost: 190,
      current_price: 190,
      market_value: 1900,
      unrealized_pnl: 0,
      unrealized_pnl_percent: 0,
    },
  ],
};

describe("format", () => {
  it("formats money for test parsing", () => {
    expect(money(10000)).toBe("$10,000.00");
    expect(money(0.1234)).toBe("$0.1234");
    expect(signedMoney(-5)).toBe("-$5.00");
    expect(signedMoney(5)).toBe("+$5.00");
    expect(signedPercent(0.2632)).toBe("+0.26%");
    expect(signedPercent(-1.5)).toBe("-1.50%");
  });
});

describe("liveValuation", () => {
  it("revalues positions with streamed prices", () => {
    const live = liveValuation(portfolio, { AAPL: quote("AAPL", 200) });
    expect(live.positions[0].market_value).toBe(2000);
    expect(live.positions[0].unrealized_pnl).toBe(100);
    expect(live.positions[0].unrealized_pnl_percent).toBeCloseTo(5.2632, 4);
    expect(live.positions_value).toBe(2000);
    expect(live.total_value).toBe(10100);
    expect(live.unrealized_pnl).toBe(100);
  });

  it("keeps the server price when no live price exists", () => {
    const live = liveValuation(portfolio, {});
    expect(live.total_value).toBe(10000);
    expect(live.positions[0].current_price).toBe(190);
  });

  it("handles a loss", () => {
    const live = liveValuation(portfolio, { AAPL: quote("AAPL", 171) });
    expect(live.unrealized_pnl).toBe(-190);
    expect(live.positions[0].unrealized_pnl_percent).toBeCloseTo(-10, 6);
  });
});

describe("price history", () => {
  it("appends new seconds and replaces within the same second", () => {
    let points = appendPoint([], { time: 1, value: 10 });
    points = appendPoint(points, { time: 1, value: 11 });
    points = appendPoint(points, { time: 2, value: 12 });
    expect(points).toEqual([
      { time: 1, value: 11 },
      { time: 2, value: 12 },
    ]);
  });

  it("drops tickers missing from an event", () => {
    const first = mergeHistory({}, { AAPL: quote("AAPL", 1, 1), MSFT: quote("MSFT", 2, 1) });
    const second = mergeHistory(first, { AAPL: quote("AAPL", 3, 2) });
    expect(Object.keys(second)).toEqual(["AAPL"]);
    expect(second.AAPL).toHaveLength(2);
  });
});

describe("treemap", () => {
  it("tiles the rect with areas proportional to value", () => {
    const cells = treemap(
      [
        { value: 50, item: "A" },
        { value: 30, item: "B" },
        { value: 20, item: "C" },
      ],
      { x: 0, y: 0, w: 100, h: 100 },
    );
    const area = Object.fromEntries(cells.map((c) => [c.item, c.w * c.h]));
    expect(area.A).toBeCloseTo(5000);
    expect(area.B).toBeCloseTo(3000);
    expect(area.C).toBeCloseTo(2000);
  });

  it("skips zero values", () => {
    expect(treemap([{ value: 0, item: "A" }], { x: 0, y: 0, w: 1, h: 1 })).toEqual([]);
  });
});
