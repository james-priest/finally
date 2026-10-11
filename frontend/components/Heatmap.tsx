import { money, signedPercent } from "@/lib/format";
import type { Position } from "@/lib/types";
import { treemap } from "@/lib/treemap";
import { Panel } from "./Panel";

// P&L percent at which a cell reaches full color.
const FULL_SCALE = 2;

/** Diverging fill: gray at 0, toward green for profit and red for loss. */
export function heatColor(pnlPercent: number): string {
  const strength = Math.round(Math.min(Math.abs(pnlPercent) / FULL_SCALE, 1) * 70);
  const hue = pnlPercent >= 0 ? "var(--color-up)" : "var(--color-down)";
  return `color-mix(in oklab, ${hue} ${strength}%, #2a3441)`;
}

export function Heatmap({ positions }: { positions: Position[] }) {
  const cells = treemap(
    positions.map((p) => ({ value: p.market_value, item: p })),
    { x: 0, y: 0, w: 100, h: 100 },
  );

  return (
    <Panel title="Positions by weight" testId="heatmap">
      {cells.length === 0 ? (
        <p className="p-3 text-sm text-ink-3">Your holdings will appear here, sized by value.</p>
      ) : (
        <div className="absolute inset-1">
          {cells.map(({ item: p, x, y, w, h }) => (
            <div
              key={p.ticker}
              data-testid={`heatmap-cell-${p.ticker}`}
              data-pnl={p.unrealized_pnl >= 0 ? "profit" : "loss"}
              title={`${p.ticker}  ${money(p.market_value)}  ${signedPercent(p.unrealized_pnl_percent)}`}
              className="absolute overflow-hidden rounded-[3px] border-2 border-panel"
              style={{
                left: `${x}%`,
                top: `${y}%`,
                width: `${w}%`,
                height: `${h}%`,
                background: heatColor(p.unrealized_pnl_percent),
              }}
            >
              {w > 14 && h > 16 && (
                <div className="p-1.5 leading-tight">
                  <div className="font-mono text-xs font-medium text-ink">{p.ticker}</div>
                  <div className="text-[11px] text-ink">{signedPercent(p.unrealized_pnl_percent)}</div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
