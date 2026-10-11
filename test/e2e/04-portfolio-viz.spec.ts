import { expect, test } from "@playwright/test";
import { closePosition, openApp, trade } from "./helpers";

const TICKERS = ["NVDA", "META"];

test.describe("portfolio visualizations", () => {
  test.beforeAll(async ({ request }) => {
    for (const ticker of TICKERS) {
      await closePosition(request, ticker);
      expect((await trade(request, ticker, "buy", 2)).status()).toBe(200);
    }
  });

  test.afterAll(async ({ request }) => {
    for (const ticker of TICKERS) await closePosition(request, ticker);
  });

  test("heatmap shows one cell per position", async ({ page }) => {
    await openApp(page);
    const heatmap = page.getByTestId("heatmap");
    await expect(heatmap).toBeVisible();
    for (const ticker of TICKERS) {
      const cell = page.getByTestId(`heatmap-cell-${ticker}`);
      await expect(cell).toBeVisible();
      const box = await cell.boundingBox();
      expect(box!.width * box!.height).toBeGreaterThan(0);
    }
  });

  test("heatmap colors cells by P&L sign", async ({ page }) => {
    await openApp(page);
    for (const ticker of TICKERS) {
      // Read label, P&L text and rendered color in one pass so a price tick can't split them.
      const cell = await page.getByTestId(`heatmap-cell-${ticker}`).evaluate((el) => {
        const ctx = document.createElement("canvas").getContext("2d")!;
        ctx.fillStyle = getComputedStyle(el).backgroundColor;
        ctx.fillRect(0, 0, 1, 1);
        const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
        return { pnl: el.getAttribute("data-pnl"), title: el.getAttribute("title") ?? "", r, g, b };
      });
      const percent = cell.title.trim().split(/\s+/).pop()!;
      expect(cell.r + cell.g + cell.b, "background resolved to a color").toBeGreaterThan(0);
      // The neutral base (#2a3441) has g - r = 10; profit mixes toward green, loss toward red.
      if (cell.pnl === "profit") {
        expect(percent.startsWith("-")).toBe(false);
        expect(cell.g - cell.r).toBeGreaterThanOrEqual(7);
      } else {
        expect(cell.pnl).toBe("loss");
        expect(percent.startsWith("-")).toBe(true);
        expect(cell.g - cell.r).toBeLessThanOrEqual(13);
      }
    }
  });

  test("positions table lists each position", async ({ page }) => {
    await openApp(page);
    for (const ticker of TICKERS) {
      await expect(page.getByTestId(`position-row-${ticker}`)).toBeVisible();
    }
  });

  test("P&L chart renders snapshot data", async ({ page, request }) => {
    const res = await request.get("/api/portfolio/history");
    expect(res.status()).toBe(200);
    const { snapshots } = await res.json();
    // One at startup plus one after each trade in beforeAll.
    expect(snapshots.length).toBeGreaterThanOrEqual(2);

    await openApp(page);
    const chart = page.getByTestId("pnl-chart");
    await expect(chart).toBeVisible();
    await expect(chart.locator("canvas, svg").first()).toBeVisible();
    expect(Number(await chart.getAttribute("data-points"))).toBeGreaterThanOrEqual(2);
  });
});
