import { expect, test } from "@playwright/test";
import { openApp, unwatch } from "./helpers";

const TICKER = "PYPL";

test.describe("watchlist", () => {
  test.beforeAll(async ({ request }) => {
    await unwatch(request, TICKER);
  });

  test.afterAll(async ({ request }) => {
    await unwatch(request, TICKER);
  });

  test("add and remove a ticker", async ({ page, request }) => {
    await openApp(page);
    const row = page.getByTestId(`watchlist-row-${TICKER}`);
    await expect(row).toHaveCount(0);

    await page.getByTestId("watchlist-add-input").fill(TICKER.toLowerCase());
    await page.getByTestId("watchlist-add-button").click();
    await expect(row).toBeVisible();
    // The SSE stream picks up the new ticker and prices it.
    await expect(page.getByTestId(`watchlist-price-${TICKER}`)).toHaveText(/\$\d/);

    const listed = await (await request.get("/api/watchlist")).json();
    expect(listed.tickers.map((t: { ticker: string }) => t.ticker)).toContain(TICKER);

    await page.getByTestId(`watchlist-remove-${TICKER}`).click();
    await expect(row).toHaveCount(0);

    const after = await (await request.get("/api/watchlist")).json();
    expect(after.tickers.map((t: { ticker: string }) => t.ticker)).not.toContain(TICKER);
  });

  test("added ticker survives a reload", async ({ page }) => {
    await openApp(page);
    await page.getByTestId("watchlist-add-input").fill(TICKER);
    await page.getByTestId("watchlist-add-button").click();
    await expect(page.getByTestId(`watchlist-row-${TICKER}`)).toBeVisible();

    await page.reload();
    await expect(page.getByTestId(`watchlist-row-${TICKER}`)).toBeVisible();
  });
});
