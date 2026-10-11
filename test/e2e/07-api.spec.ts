import { expect, test } from "@playwright/test";
import { DEFAULT_TICKERS, closePosition, trade, unwatch } from "./helpers";

test.describe("API", () => {
  test("health", async ({ request }) => {
    const res = await request.get("/api/health");
    expect(res.status()).toBe(200);
    expect((await res.json()).status).toBe("ok");
  });

  test("portfolio shape", async ({ request }) => {
    const res = await request.get("/api/portfolio");
    expect(res.status()).toBe(200);
    const body = await res.json();
    for (const key of ["cash_balance", "positions_value", "total_value", "unrealized_pnl", "positions"]) {
      expect(body).toHaveProperty(key);
    }
  });

  test("watchlist lists default tickers with quotes", async ({ request }) => {
    const res = await request.get("/api/watchlist");
    expect(res.status()).toBe(200);
    const { tickers } = await res.json();
    const symbols = tickers.map((t: { ticker: string }) => t.ticker);
    for (const ticker of DEFAULT_TICKERS) expect(symbols).toContain(ticker);
    const aapl = tickers.find((t: { ticker: string }) => t.ticker === "AAPL");
    expect(aapl.quote.price).toBeGreaterThan(0);
  });

  test("invalid trades are rejected", async ({ request }) => {
    expect((await trade(request, "AAPL", "buy", 0)).status()).toBe(422);
    expect((await trade(request, "AAPL", "buy", -1)).status()).toBe(422);
    expect((await request.post("/api/portfolio/trade", { data: { ticker: "AAPL", side: "hold", quantity: 1 } })).status()).toBe(422);
    expect((await trade(request, "NOT A TICKER!", "buy", 1)).status()).toBe(422);

    const tooExpensive = await trade(request, "AAPL", "buy", 1_000_000);
    expect(tooExpensive.status()).toBe(400);
    expect((await tooExpensive.json()).detail).toBeTruthy();

    await closePosition(request, "V");
    const notOwned = await trade(request, "V", "sell", 1);
    expect(notOwned.status()).toBe(400);
    expect((await notOwned.json()).detail).toBeTruthy();
  });

  test("buy then sell returns trade and portfolio", async ({ request }) => {
    await closePosition(request, "AMZN");
    const buy = await trade(request, "AMZN", "buy", 0.5);
    expect(buy.status()).toBe(200);
    const body = await buy.json();
    expect(body.trade).toMatchObject({ ticker: "AMZN", side: "buy", quantity: 0.5 });
    expect(body.trade.price).toBeGreaterThan(0);
    expect(body.portfolio.positions.find((p: { ticker: string }) => p.ticker === "AMZN").quantity).toBe(0.5);

    const sell = await trade(request, "AMZN", "sell", 0.5);
    expect(sell.status()).toBe(200);
    expect((await sell.json()).portfolio.positions.find((p: { ticker: string }) => p.ticker === "AMZN")).toBeUndefined();
  });

  test("watchlist add conflicts and remove misses", async ({ request }) => {
    const ticker = "DIS";
    await unwatch(request, ticker);

    const added = await request.post("/api/watchlist", { data: { ticker } });
    expect(added.status()).toBe(201);
    expect((await added.json()).ticker).toBe(ticker);

    expect((await request.post("/api/watchlist", { data: { ticker } })).status()).toBe(409);
    expect((await request.post("/api/watchlist", { data: { ticker: "AAPL" } })).status()).toBe(409);
    expect((await request.post("/api/watchlist", { data: { ticker: "NOT A TICKER!" } })).status()).toBe(422);

    expect((await request.delete(`/api/watchlist/${ticker}`)).status()).toBe(204);
    expect((await request.delete(`/api/watchlist/${ticker}`)).status()).toBe(404);
  });

  test("portfolio history is oldest first", async ({ request }) => {
    const res = await request.get("/api/portfolio/history");
    expect(res.status()).toBe(200);
    const { snapshots } = await res.json();
    expect(snapshots.length).toBeGreaterThan(0);
    const times = snapshots.map((s: { recorded_at: string }) => Date.parse(s.recorded_at));
    expect(times).toEqual([...times].sort((a, b) => a - b));
  });

  test("chat responds with the contract shape and history", async ({ request }) => {
    const res = await request.post("/api/chat", { data: { message: "hello" } });
    expect(res.status()).toBe(200);
    const reply = await res.json();
    expect(reply).toMatchObject({
      role: "assistant",
      content: "Mock: I received your message.",
      actions: { trades: [], watchlist_changes: [] },
    });

    const history = await (await request.get("/api/chat")).json();
    const last = history.messages.slice(-2);
    expect(last[0]).toMatchObject({ role: "user", content: "hello", actions: null });
    expect(last[1].id).toBe(reply.id);
  });

  test("SSE stream sends price events", async ({ page }) => {
    // The stream never ends, so read the first event from the browser.
    await page.goto("/api/health");
    const first = await page.evaluate(
      () =>
        new Promise<Record<string, { price: number }>>((resolve, reject) => {
          const source = new EventSource("/api/stream/prices");
          source.onmessage = (e) => {
            source.close();
            resolve(JSON.parse(e.data));
          };
          setTimeout(() => reject(new Error("no SSE event within 5s")), 5_000);
        }),
    );
    expect(first.AAPL.price).toBeGreaterThan(0);
  });
});
