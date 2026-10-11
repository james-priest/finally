"use client";

import { useMemo } from "react";
import { money } from "@/lib/format";
import type { Snapshot } from "@/lib/types";
import { appendPoint, type PricePoint } from "@/lib/usePriceStream";
import { Panel } from "./Panel";
import { TimeSeriesChart } from "./TimeSeriesChart";

export function PnlChart({ snapshots }: { snapshots: Snapshot[] }) {
  const points = useMemo(
    () =>
      snapshots.reduce<PricePoint[]>(
        (acc, s) =>
          appendPoint(acc, {
            time: Math.floor(Date.parse(s.recorded_at) / 1000),
            value: s.total_value,
          }),
        [],
      ),
    [snapshots],
  );
  const latest = points.at(-1);

  return (
    <Panel
      title="Portfolio value"
      aside={latest && <span className="text-xs text-ink-2">{money(latest.value)}</span>}
    >
      <div data-testid="pnl-chart" data-points={points.length} className="absolute inset-0 p-1">
        {points.length > 0 ? (
          <TimeSeriesChart points={points} color="#ecad0a" />
        ) : (
          <p className="p-3 text-sm text-ink-3">Value snapshots appear here every 30 seconds.</p>
        )}
      </div>
    </Panel>
  );
}
