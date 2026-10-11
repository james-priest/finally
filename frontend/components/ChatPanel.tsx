"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { money, quantity } from "@/lib/format";
import type { ChatMessage, TradeAction, WatchlistAction } from "@/lib/types";

function tradeText(t: TradeAction): string {
  const what = `${quantity(t.quantity)} ${t.ticker}`;
  if (t.status === "failed") return `${t.side === "buy" ? "Buy" : "Sell"} ${what} failed: ${t.error}`;
  const price = t.price === null ? "" : ` at ${money(t.price)}`;
  return `${t.side === "buy" ? "Bought" : "Sold"} ${what}${price}`;
}

function watchlistText(w: WatchlistAction): string {
  if (w.status === "failed") return `${w.action === "add" ? "Add" : "Remove"} ${w.ticker} failed: ${w.error}`;
  return w.action === "add" ? `Added ${w.ticker} to watchlist` : `Removed ${w.ticker} from watchlist`;
}

function Actions({ actions }: { actions: ChatMessage["actions"] }) {
  if (!actions) return null;
  const items = [
    ...actions.trades.map((t) => ({ status: t.status, text: tradeText(t) })),
    ...actions.watchlist_changes.map((w) => ({ status: w.status, text: watchlistText(w) })),
  ];
  if (items.length === 0) return null;
  return (
    <ul className="mt-1.5 space-y-1">
      {items.map((item, i) => (
        <li
          key={i}
          data-testid="chat-action"
          data-status={item.status}
          className={`flex items-center gap-2 rounded border px-2 py-1 text-xs ${
            item.status === "executed" ? "border-up/40 text-up" : "border-down/40 text-down"
          }`}
        >
          <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />
          {item.text}
        </li>
      ))}
    </ul>
  );
}

export function ChatPanel({ onActions }: { onActions: () => void }) {
  const [open, setOpen] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.getChat().then((r) => setMessages(r.messages));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages, loading, open]);

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    const sent: ChatMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content: text,
      actions: null,
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, sent]);
    setInput("");
    setError(null);
    setLoading(true);
    try {
      const reply = await api.sendChat(text);
      setMessages((m) => [...m, reply]);
      if (reply.actions && (reply.actions.trades.length || reply.actions.watchlist_changes.length)) {
        onActions();
      }
    } catch (err) {
      setError(`Message not sent: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return (
      <aside data-testid="chat-panel" data-open="false" className="flex w-10 shrink-0 flex-col border-l border-line bg-panel">
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="Open assistant"
          className="h-full text-[13px] font-medium text-ink-2 [writing-mode:vertical-rl] hover:bg-raised hover:text-ink"
        >
          Assistant
        </button>
      </aside>
    );
  }

  return (
    <aside data-testid="chat-panel" data-open="true" className="flex w-[340px] shrink-0 flex-col border-l border-line bg-panel">
      <header className="flex h-8 shrink-0 items-center justify-between border-b border-line px-3">
        <h2 className="text-[13px] font-medium text-ink-2">Assistant</h2>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Collapse assistant"
          className="rounded px-1.5 text-ink-3 hover:bg-raised hover:text-ink"
        >
          &rsaquo;
        </button>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 text-[13px] leading-relaxed">
        {messages.length === 0 && !loading && (
          <p className="text-ink-3">
            Ask about your portfolio, or tell me to buy, sell, or watch a ticker.
          </p>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            data-testid="chat-message"
            data-role={m.role}
            className={m.role === "user" ? "ml-8 rounded bg-raised px-2.5 py-1.5 text-ink" : "border-l-2 border-brand pl-2.5 text-ink"}
          >
            <p className="whitespace-pre-wrap">{m.content}</p>
            <Actions actions={m.actions} />
          </div>
        ))}
        {loading && (
          <div data-testid="chat-loading" className="flex items-center gap-1 border-l-2 border-brand pl-2.5 text-ink-3">
            <span className="loading-dot">Thinking</span>
          </div>
        )}
        {error && <p className="text-down">{error}</p>}
        <div ref={endRef} />
      </div>

      <form onSubmit={send} className="flex shrink-0 gap-1.5 border-t border-line p-2">
        <input
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Message FinAlly"
          aria-label="Message"
          className="min-w-0 flex-1 rounded border border-line bg-page px-2 py-1.5 text-[13px] placeholder:text-ink-3"
        />
        <button
          type="submit"
          data-testid="chat-send"
          disabled={loading}
          className="rounded bg-submit px-3 py-1.5 text-[13px] font-medium text-white hover:bg-submit-hover disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </aside>
  );
}
