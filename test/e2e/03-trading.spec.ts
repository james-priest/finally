import { expect, test, type Page } from "@playwright/test";
import { closePosition, moneyOf, openApp, positionQuantity } from "./helpers";

const TICKER = "JPM";

async function submitTrade(page: Page, side: "buy" | "sell", quantity: number) {
  await page.getByTestId("trade-ticker-input").fill(TICKER);
  await page.getByTestId("trade-quantity-input").fill(String(quantity));
  await page.getByTestId(`trade-${side}-button`).click();
}

test.describe.configure({ mode: "serial" });

test.describe("trading", () => {
  test.beforeAll(async ({ request }) => {
    await closePosition(request, TICKER);
  });

  test.afterAll(async ({ request }) => {
    await closePosition(request, TICKER);
  });

  test.beforeEach(async ({ page }) => {
    await openApp(page);
  });

  test("buy shares: cash decreases, position row and heatmap cell appear", async ({ page, request }) => {
    const cash = page.getByTestId("header-cash");
    await expect(cash).toHaveText(/\$\d/);
    const cashBefore = await moneyOf(cash);

    await submitTrade(page, "buy", 3);

    await expect(page.getByTestId(`position-row-${TICKER}`)).toBeVisible();
    await expect(page.getByTestId(`heatmap-cell-${TICKER}`)).toBeVisible();
    await expect.poll(() => moneyOf(cash)).toBeLessThan(cashBefore);
    expect(await positionQuantity(request, TICKER)).toBe(3);
  });

  test("partial sell: cash increases, position updates", async ({ page, request }) => {
    const cash = page.getByTestId("header-cash");
    await expect(cash).toHaveText(/\$\d/);
    const cashBefore = await moneyOf(cash);

    await submitTrade(page, "sell", 1);

    await expect.poll(() => moneyOf(cash)).toBeGreaterThan(cashBefore);
    await expect.poll(() => positionQuantity(request, TICKER)).toBe(2);
    await expect(page.getByTestId(`position-row-${TICKER}`)).toBeVisible();
  });

  test("selling more than owned shows a trade error", async ({ page, request }) => {
    await submitTrade(page, "sell", 1000);
    await expect(page.getByTestId("trade-error")).toContainText(/insufficient shares/i);
    expect(await positionQuantity(request, TICKER)).toBe(2);
  });

  test("selling the rest removes the position", async ({ page, request }) => {
    const cash = page.getByTestId("header-cash");
    await expect(cash).toHaveText(/\$\d/);
    const cashBefore = await moneyOf(cash);

    await submitTrade(page, "sell", 2);

    await expect(page.getByTestId(`position-row-${TICKER}`)).toHaveCount(0);
    await expect(page.getByTestId(`heatmap-cell-${TICKER}`)).toHaveCount(0);
    await expect.poll(() => moneyOf(cash)).toBeGreaterThan(cashBefore);
    expect(await positionQuantity(request, TICKER)).toBe(0);
  });
});
