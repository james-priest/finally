import { expect, test, type Page } from "@playwright/test";
import { closePosition, openApp, positionQuantity, unwatch } from "./helpers";

// Runs against LLM_MOCK=true: replies follow TEAM_CONTRACT.md §5.

async function send(page: Page, message: string) {
  const assistant = page.locator('[data-testid="chat-message"][data-role="assistant"]');
  const before = await assistant.count();
  await page.getByTestId("chat-input").fill(message);
  await page.getByTestId("chat-send").click();
  await expect(assistant).toHaveCount(before + 1);
  return assistant.last();
}

test.describe.configure({ mode: "serial" });

test.describe("AI chat (mock)", () => {
  test.beforeAll(async ({ request }) => {
    await closePosition(request, "AAPL");
    await unwatch(request, "SHOP");
  });

  test.afterAll(async ({ request }) => {
    await closePosition(request, "AAPL");
    await unwatch(request, "SHOP");
  });

  test.beforeEach(async ({ page }) => {
    await openApp(page);
  });

  test("buy via chat executes the trade and shows it inline", async ({ page, request }) => {
    const reply = await send(page, "buy 5 AAPL");
    await expect(reply).toContainText("Mock: buying 5 AAPL");
    await expect(reply.getByTestId("chat-action")).toContainText("AAPL");
    await expect(reply.getByTestId("chat-action")).toHaveAttribute("data-status", "executed");
    await expect(page.locator('[data-testid="chat-message"][data-role="user"]').last()).toContainText("buy 5 AAPL");

    await expect(page.getByTestId("position-row-AAPL")).toBeVisible();
    expect(await positionQuantity(request, "AAPL")).toBe(5);
  });

  test("chat history survives a reload", async ({ page }) => {
    await expect(page.locator('[data-testid="chat-message"][data-role="assistant"]').last()).toContainText(
      "Mock: buying 5 AAPL",
    );
  });

  test("sell via chat closes the position", async ({ page, request }) => {
    const reply = await send(page, "sell 5 AAPL");
    await expect(reply).toContainText("Mock: selling 5 AAPL");
    await expect(reply.getByTestId("chat-action")).toHaveAttribute("data-status", "executed");
    await expect(page.getByTestId("position-row-AAPL")).toHaveCount(0);
    expect(await positionQuantity(request, "AAPL")).toBe(0);
  });

  test("failed trade is reported inline", async ({ page }) => {
    const reply = await send(page, "sell 1000 AAPL");
    const action = reply.getByTestId("chat-action");
    await expect(action).toHaveAttribute("data-status", "failed");
    await expect(action).toContainText(/insufficient/i);
  });

  test("watchlist add and remove via chat", async ({ page }) => {
    const added = await send(page, "add SHOP");
    await expect(added).toContainText("Mock: adding SHOP to the watchlist.");
    await expect(added.getByTestId("chat-action")).toHaveAttribute("data-status", "executed");
    await expect(page.getByTestId("watchlist-row-SHOP")).toBeVisible();

    const removed = await send(page, "remove SHOP");
    await expect(removed).toContainText("Mock: removing SHOP from the watchlist.");
    await expect(page.getByTestId("watchlist-row-SHOP")).toHaveCount(0);
  });

  test("plain message gets the default reply with no actions", async ({ page }) => {
    const reply = await send(page, "how is my portfolio doing?");
    await expect(reply).toContainText("Mock: I received your message.");
    await expect(reply.getByTestId("chat-action")).toHaveCount(0);
  });
});
