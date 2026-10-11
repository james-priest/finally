import { expect, test } from "@playwright/test";

const STREAM = "**/api/stream/prices";

// context.setOffline() fails new requests but does not cut an SSE response that is already
// streaming, so the test owns the stream instead: the first connection gets a finite body
// (it opens, delivers one snapshot and ends, like a server restart), reconnects are refused,
// then the real stream is let through.
test.describe("SSE resilience", () => {
  test("status shows reconnecting when the stream drops, then recovers", async ({ page, request }) => {
    const { tickers } = await (await request.get("/api/watchlist")).json();
    const snapshot = Object.fromEntries(
      tickers.filter((t: { quote: unknown }) => t.quote).map((t: { ticker: string; quote: unknown }) => [t.ticker, t.quote]),
    );

    let live = false;
    let served = false;
    await page.route(STREAM, async (route) => {
      if (live) return route.continue();
      if (served) return route.abort("connectionrefused");
      served = true;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: `retry: 1000\ndata: ${JSON.stringify(snapshot)}\n\n`,
      });
    });

    await page.goto("/");
    const status = page.getByTestId("connection-status");
    const price = page.getByTestId("watchlist-price-AAPL");

    // The finite connection delivered its snapshot, then ended.
    await expect(price).toHaveText(/\$\d/);
    await expect(status).toHaveAttribute("data-status", "reconnecting");
    // Still retrying, not given up, while reconnects are refused.
    await page.waitForTimeout(3_000);
    await expect(status).toHaveAttribute("data-status", "reconnecting");

    live = true;
    await expect(status).toHaveAttribute("data-status", "connected", { timeout: 15_000 });
    const resumed = await price.textContent();
    await expect.poll(() => price.textContent()).not.toBe(resumed);
  });
});
