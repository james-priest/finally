import { expect, test } from "@playwright/test";
import { DEFAULT_TICKERS, moneyOf, openApp } from "./helpers";

// Requires a fresh database: run this file first (it is, by name) against a new container.
test.describe("fresh start", () => {
  test.beforeEach(async ({ page }) => {
    await openApp(page);
  });

  test("shows the 10 default tickers in order", async ({ page }) => {
    const watchlist = page.getByTestId("watchlist");
    await expect(watchlist.locator('[data-testid^="watchlist-row-"]')).toHaveCount(DEFAULT_TICKERS.length);
    for (const ticker of DEFAULT_TICKERS) {
      await expect(page.getByTestId(`watchlist-row-${ticker}`)).toBeVisible();
    }
  });

  test("shows $10,000.00 cash and total value with no positions", async ({ page }) => {
    await expect(page.getByTestId("header-cash")).toHaveText(/\$10,000\.00/);
    await expect(page.getByTestId("header-total-value")).toHaveText(/\$10,000\.00/);
    await expect(page.getByTestId("positions-table").locator('[data-testid^="position-row-"]')).toHaveCount(0);
  });

  test("prices stream and change", async ({ page }) => {
    for (const ticker of DEFAULT_TICKERS) {
      await expect(page.getByTestId(`watchlist-price-${ticker}`)).toHaveText(/\$\d/);
    }
    const prices = page.locator('[data-testid^="watchlist-price-"]');
    const first = await prices.allTextContents();
    await expect.poll(async () => (await prices.allTextContents()).join("|")).not.toBe(first.join("|"));
    expect(await moneyOf(page.getByTestId("watchlist-price-AAPL"))).toBeGreaterThan(0);
  });

  test("clicking a ticker selects it in the main chart", async ({ page }) => {
    await page.getByTestId("watchlist-row-MSFT").click();
    await expect(page.getByTestId("main-chart")).toHaveAttribute("data-ticker", "MSFT");
    await page.getByTestId("watchlist-row-TSLA").click();
    await expect(page.getByTestId("main-chart")).toHaveAttribute("data-ticker", "TSLA");
  });

  test("P&L chart and chat panel render", async ({ page }) => {
    await expect(page.getByTestId("pnl-chart")).toBeVisible();
    await expect(page.getByTestId("chat-panel")).toBeVisible();
    await expect(page.getByTestId("chat-input")).toBeVisible();
  });
});
