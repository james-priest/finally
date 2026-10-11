import type { ChatMessage, Portfolio, Side, Snapshot, Trade, WatchlistEntry } from "./types";

export class ApiError extends Error {}

function detailMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors (422) are a list of {msg} objects.
  if (Array.isArray(detail)) return detail.map((d: { msg: string }) => d.msg).join("; ");
  return `Request failed (${status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(detailMessage(body, res.status));
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  getPortfolio: () => request<Portfolio>("/api/portfolio"),
  getHistory: () => request<{ snapshots: Snapshot[] }>("/api/portfolio/history"),
  trade: (ticker: string, quantity: number, side: Side) =>
    request<{ trade: Trade; portfolio: Portfolio }>("/api/portfolio/trade", {
      method: "POST",
      body: JSON.stringify({ ticker, quantity, side }),
    }),
  getWatchlist: () => request<{ tickers: WatchlistEntry[] }>("/api/watchlist"),
  addTicker: (ticker: string) =>
    request<WatchlistEntry>("/api/watchlist", { method: "POST", body: JSON.stringify({ ticker }) }),
  removeTicker: (ticker: string) =>
    request<void>(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" }),
  getChat: () => request<{ messages: ChatMessage[] }>("/api/chat"),
  sendChat: (message: string) =>
    request<ChatMessage>("/api/chat", { method: "POST", body: JSON.stringify({ message }) }),
};
