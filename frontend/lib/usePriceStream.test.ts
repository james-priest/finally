import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePriceStream } from "./usePriceStream";

class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }
}

const latest = () => FakeEventSource.instances.at(-1)!;

describe("usePriceStream", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("stores prices and history from messages", () => {
    const { result } = renderHook(() => usePriceStream());
    expect(result.current.status).toBe("reconnecting");
    const update = { ticker: "AAPL", price: 190.5, timestamp: 1000 };
    act(() => latest().onmessage!({ data: JSON.stringify({ AAPL: update }) }));
    expect(result.current.status).toBe("connected");
    expect(result.current.prices.AAPL.price).toBe(190.5);
    expect(result.current.history.AAPL).toEqual([{ time: 1000, value: 190.5 }]);
  });

  it("shows reconnecting while the browser retries", () => {
    const { result } = renderHook(() => usePriceStream());
    act(() => latest().onopen!());
    act(() => latest().onerror!());
    expect(result.current.status).toBe("reconnecting");
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("reconnects itself after the browser gives up", () => {
    const { result } = renderHook(() => usePriceStream());
    act(() => {
      latest().readyState = FakeEventSource.CLOSED;
      latest().onerror!();
    });
    expect(result.current.status).toBe("disconnected");

    act(() => vi.advanceTimersByTime(2000));
    expect(FakeEventSource.instances).toHaveLength(2);
    act(() => latest().onopen!());
    expect(result.current.status).toBe("connected");
  });
});
