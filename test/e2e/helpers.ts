import { expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";

export const DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"];

/** Parse "$10,000.00" (or "-$5.00") into a number. */
export function parseMoney(text: string | null): number {
  const cleaned = (text ?? "").replace(/[^0-9.-]/g, "");
  const value = Number.parseFloat(cleaned);
  if (Number.isNaN(value)) throw new Error(`Not a money value: ${JSON.stringify(text)}`);
  return value;
}

export async function moneyOf(locator: Locator): Promise<number> {
  return parseMoney(await locator.textContent());
}

/** Open the app and wait until the SSE stream reports connected. */
export async function openApp(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByTestId("connection-status")).toHaveAttribute("data-status", "connected");
}

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
}

export interface Portfolio {
  cash_balance: number;
  total_value: number;
  positions: Position[];
}

export async function getPortfolio(request: APIRequestContext): Promise<Portfolio> {
  const res = await request.get("/api/portfolio");
  expect(res.status()).toBe(200);
  return res.json();
}

export async function positionQuantity(request: APIRequestContext, ticker: string): Promise<number> {
  const portfolio = await getPortfolio(request);
  return portfolio.positions.find((p) => p.ticker === ticker)?.quantity ?? 0;
}

export async function trade(request: APIRequestContext, ticker: string, side: "buy" | "sell", quantity: number) {
  return request.post("/api/portfolio/trade", { data: { ticker, side, quantity } });
}

/** Sell any open position in `ticker` so later specs see a clean slate. */
export async function closePosition(request: APIRequestContext, ticker: string): Promise<void> {
  const quantity = await positionQuantity(request, ticker);
  if (quantity > 0) expect((await trade(request, ticker, "sell", quantity)).status()).toBe(200);
}

/** Remove `ticker` from the watchlist if present. */
export async function unwatch(request: APIRequestContext, ticker: string): Promise<void> {
  const res = await request.delete(`/api/watchlist/${ticker}`);
  expect([204, 404]).toContain(res.status());
}
