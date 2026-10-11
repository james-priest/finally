"use client";

import { useEffect, useState } from "react";
import type { PriceMap, PriceUpdate } from "./types";

export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";

export interface PricePoint {
  time: number; // Unix seconds
  value: number;
}

export type PriceHistory = Record<string, PricePoint[]>;

const MAX_POINTS = 900;
const RECONNECT_MS = 2000;

/** Append a point, replacing the last one when it falls in the same second. */
export function appendPoint(points: PricePoint[], point: PricePoint): PricePoint[] {
  const last = points.at(-1);
  const next =
    last && point.time <= last.time
      ? [...points.slice(0, -1), { time: last.time, value: point.value }]
      : [...points, point];
  return next.length > MAX_POINTS ? next.slice(-MAX_POINTS) : next;
}

/** Fold one SSE event into the history. Tickers missing from the event are dropped. */
export function mergeHistory(history: PriceHistory, event: PriceMap): PriceHistory {
  const next: PriceHistory = {};
  for (const update of Object.values(event)) {
    next[update.ticker] = appendPoint(history[update.ticker] ?? [], toPoint(update));
  }
  return next;
}

function toPoint(update: PriceUpdate): PricePoint {
  return { time: Math.floor(update.timestamp), value: update.price };
}

/** Live prices from `/api/stream/prices`, with per-ticker history accumulated since page load. */
export function usePriceStream() {
  const [prices, setPrices] = useState<PriceMap>({});
  const [history, setHistory] = useState<PriceHistory>({});
  const [status, setStatus] = useState<ConnectionStatus>("reconnecting");

  useEffect(() => {
    let source: EventSource;
    let retry: ReturnType<typeof setTimeout> | undefined;

    function connect() {
      source = new EventSource("/api/stream/prices");
      source.onopen = () => setStatus("connected");
      source.onerror = () => {
        // EventSource retries on its own unless the browser gave up (CLOSED); then we retry.
        if (source.readyState === EventSource.CLOSED) {
          setStatus("disconnected");
          retry = setTimeout(connect, RECONNECT_MS);
        } else {
          setStatus("reconnecting");
        }
      };
      source.onmessage = (e: MessageEvent<string>) => {
        const event = JSON.parse(e.data) as PriceMap;
        setPrices(event);
        setHistory((prev) => mergeHistory(prev, event));
        setStatus("connected");
      };
    }

    connect();
    return () => {
      clearTimeout(retry);
      source.close();
    };
  }, []);

  return { prices, history, status };
}
