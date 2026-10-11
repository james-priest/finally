import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Portfolio, Position, PriceUpdate, WatchlistEntry } from "@/lib/types";
import { Header } from "./Header";
import { Heatmap } from "./Heatmap";
import { PositionsTable } from "./PositionsTable";
import { PriceCell } from "./PriceCell";
import { TradeBar } from "./TradeBar";
import { Watchlist } from "./Watchlist";

function quote(ticker: string, price: number, dayChange = 0.5): PriceUpdate {
  return {
    ticker,
    price,
    previous_price: price,
    prev_close: price,
    change: 0,
    day_change_percent: dayChange,
    direction: "flat",
    timestamp: 1000,
  };
}

const positions: Position[] = [
  {
    ticker: "AAPL",
    quantity: 10,
    avg_cost: 190,
    current_price: 200,
    market_value: 2000,
    unrealized_pnl: 100,
    unrealized_pnl_percent: 5.2632,
  },
  {
    ticker: "TSLA",
    quantity: 2,
    avg_cost: 250,
    current_price: 240,
    market_value: 480,
    unrealized_pnl: -20,
    unrealized_pnl_percent: -4,
  },
];

describe("PriceCell", () => {
  it("flashes up then down on price changes", () => {
    const { rerender } = render(<PriceCell price={100} testId="p" />);
    expect(screen.getByTestId("p")).not.toHaveAttribute("data-flash");
    expect(screen.getByTestId("p")).toHaveTextContent("$100.00");

    rerender(<PriceCell price={101} testId="p" />);
    expect(screen.getByTestId("p")).toHaveAttribute("data-flash", "up");
    expect(screen.getByTestId("p")).toHaveClass("flash-up");

    rerender(<PriceCell price={100.5} testId="p" />);
    expect(screen.getByTestId("p")).toHaveAttribute("data-flash", "down");
    expect(screen.getByTestId("p")).toHaveClass("flash-down");
  });

  it("does not flash when the price is unchanged", () => {
    const { rerender } = render(<PriceCell price={100} testId="p" />);
    rerender(<PriceCell price={100} testId="p" />);
    expect(screen.getByTestId("p")).not.toHaveAttribute("data-flash");
  });
});

describe("Header", () => {
  const portfolio: Portfolio = {
    cash_balance: 8100,
    positions_value: 2480,
    total_value: 10580,
    unrealized_pnl: 80,
    positions,
  };

  it("shows total value, cash and connection status", () => {
    render(<Header portfolio={portfolio} status="reconnecting" />);
    expect(screen.getByTestId("header-total-value")).toHaveTextContent("$10,580.00");
    expect(screen.getByTestId("header-cash")).toHaveTextContent("$8,100.00");
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "reconnecting");
  });
});

describe("Watchlist", () => {
  const entries: WatchlistEntry[] = [
    { ticker: "AAPL", added_at: "", quote: null },
    { ticker: "MSFT", added_at: "", quote: quote("MSFT", 420) },
  ];

  function renderWatchlist(overrides = {}) {
    const props = {
      entries,
      prices: { AAPL: quote("AAPL", 190.5, -0.25) },
      history: {},
      selected: "AAPL",
      onSelect: vi.fn(),
      onAdd: vi.fn().mockResolvedValue(undefined),
      onRemove: vi.fn().mockResolvedValue(undefined),
      ...overrides,
    };
    render(<Watchlist {...props} />);
    return props;
  }

  it("renders rows with live prices, falling back to the REST quote", () => {
    renderWatchlist();
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveTextContent("$190.50");
    expect(screen.getByTestId("watchlist-price-MSFT")).toHaveTextContent("$420.00");
    expect(within(screen.getByTestId("watchlist-row-AAPL")).getByText("-0.25%")).toHaveClass("text-down");
  });

  it("selects, adds and removes tickers", async () => {
    const user = userEvent.setup();
    const props = renderWatchlist();
    await user.click(screen.getByTestId("watchlist-row-MSFT"));
    expect(props.onSelect).toHaveBeenCalledWith("MSFT");

    await user.type(screen.getByTestId("watchlist-add-input"), "pypl");
    await user.click(screen.getByTestId("watchlist-add-button"));
    expect(props.onAdd).toHaveBeenCalledWith("PYPL");

    await user.click(screen.getByTestId("watchlist-remove-AAPL"));
    expect(props.onRemove).toHaveBeenCalledWith("AAPL");
    expect(props.onSelect).toHaveBeenCalledTimes(1);
  });

  it("shows the error when adding fails", async () => {
    const user = userEvent.setup();
    renderWatchlist({ onAdd: vi.fn().mockRejectedValue(new Error("MSFT is already on the watchlist")) });
    await user.type(screen.getByTestId("watchlist-add-input"), "MSFT");
    await user.click(screen.getByTestId("watchlist-add-button"));
    expect(await screen.findByText("MSFT is already on the watchlist")).toBeInTheDocument();
  });
});

describe("PositionsTable", () => {
  it("renders a row per position with P&L", () => {
    render(<PositionsTable positions={positions} onSelect={vi.fn()} />);
    const aapl = screen.getByTestId("position-row-AAPL");
    expect(aapl).toHaveTextContent("$190.00");
    expect(aapl).toHaveTextContent("+$100.00");
    expect(aapl).toHaveTextContent("+5.26%");
    expect(screen.getByTestId("position-row-TSLA")).toHaveTextContent("-$20.00");
  });

  it("shows an empty state", () => {
    render(<PositionsTable positions={[]} onSelect={vi.fn()} />);
    expect(screen.getByText(/No positions yet/)).toBeInTheDocument();
  });
});

describe("Heatmap", () => {
  it("renders a cell per position colored by P&L", () => {
    render(<Heatmap positions={positions} />);
    expect(screen.getByTestId("heatmap-cell-AAPL")).toHaveAttribute("data-pnl", "profit");
    expect(screen.getByTestId("heatmap-cell-TSLA")).toHaveAttribute("data-pnl", "loss");
  });
});

describe("TradeBar", () => {
  it("submits a buy and reports the fill", async () => {
    const user = userEvent.setup();
    const onTrade = vi.fn().mockResolvedValue({
      id: "1",
      ticker: "AAPL",
      side: "buy",
      quantity: 5,
      price: 190,
      executed_at: "",
    });
    render(<TradeBar ticker="AAPL" onTickerChange={vi.fn()} onTrade={onTrade} />);
    await user.clear(screen.getByTestId("trade-quantity-input"));
    await user.type(screen.getByTestId("trade-quantity-input"), "5");
    await user.click(screen.getByTestId("trade-buy-button"));
    expect(onTrade).toHaveBeenCalledWith("AAPL", 5, "buy");
    expect(await screen.findByText("Bought 5 AAPL at $190.00")).toBeInTheDocument();
  });

  it("shows the server error on a failed sell", async () => {
    const user = userEvent.setup();
    const onTrade = vi.fn().mockRejectedValue(new Error("Insufficient shares"));
    render(<TradeBar ticker="AAPL" onTickerChange={vi.fn()} onTrade={onTrade} />);
    await user.click(screen.getByTestId("trade-sell-button"));
    expect(await screen.findByTestId("trade-error")).toHaveTextContent("Insufficient shares");
  });
});
