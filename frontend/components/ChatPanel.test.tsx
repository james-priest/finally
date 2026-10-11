import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";
import { ChatPanel } from "./ChatPanel";

vi.mock("@/lib/api", () => ({ api: { getChat: vi.fn(), sendChat: vi.fn() } }));

const reply: ChatMessage = {
  id: "a1",
  role: "assistant",
  content: "Mock: buying 5 AAPL.",
  actions: {
    trades: [{ ticker: "AAPL", side: "buy", quantity: 5, status: "executed", price: 190, error: null }],
    watchlist_changes: [
      { ticker: "PYPL", action: "add", status: "failed", error: "PYPL is already on the watchlist" },
    ],
  },
  created_at: "",
};

describe("ChatPanel", () => {
  beforeEach(() => {
    vi.mocked(api.getChat).mockResolvedValue({
      messages: [{ id: "u0", role: "user", content: "hello", actions: null, created_at: "" }],
    });
  });

  it("loads history", async () => {
    render(<ChatPanel onActions={vi.fn()} />);
    const msg = await screen.findByTestId("chat-message");
    expect(msg).toHaveAttribute("data-role", "user");
    expect(msg).toHaveTextContent("hello");
  });

  it("shows loading, then the reply with inline actions", async () => {
    let resolve: (m: ChatMessage) => void = () => {};
    vi.mocked(api.sendChat).mockReturnValue(new Promise((r) => (resolve = r)));
    const onActions = vi.fn();
    const user = userEvent.setup();
    render(<ChatPanel onActions={onActions} />);
    await screen.findByTestId("chat-message");

    await user.type(screen.getByTestId("chat-input"), "buy 5 AAPL");
    await user.click(screen.getByTestId("chat-send"));
    expect(screen.getByTestId("chat-loading")).toBeInTheDocument();
    expect(screen.getAllByTestId("chat-message")).toHaveLength(2);
    expect(api.sendChat).toHaveBeenCalledWith("buy 5 AAPL");

    resolve(reply);
    const actions = await screen.findAllByTestId("chat-action");
    expect(screen.queryByTestId("chat-loading")).not.toBeInTheDocument();
    expect(actions[0]).toHaveTextContent("Bought 5 AAPL at $190.00");
    expect(actions[0]).toHaveAttribute("data-status", "executed");
    expect(actions[1]).toHaveTextContent("Add PYPL failed: PYPL is already on the watchlist");
    expect(screen.getAllByTestId("chat-message").at(-1)).toHaveAttribute("data-role", "assistant");
    expect(onActions).toHaveBeenCalledTimes(1);
  });

  it("collapses and reopens", async () => {
    const user = userEvent.setup();
    render(<ChatPanel onActions={vi.fn()} />);
    await user.click(screen.getByLabelText("Collapse assistant"));
    expect(screen.getByTestId("chat-panel")).toHaveAttribute("data-open", "false");
    expect(screen.queryByTestId("chat-input")).not.toBeInTheDocument();
    await user.click(screen.getByLabelText("Open assistant"));
    expect(screen.getByTestId("chat-input")).toBeInTheDocument();
  });
});
