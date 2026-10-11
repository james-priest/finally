import { money, quantity, signedMoney, signedPercent, trendClass } from "@/lib/format";
import type { Position } from "@/lib/types";
import { Panel } from "./Panel";

interface PositionsTableProps {
  positions: Position[];
  onSelect: (ticker: string) => void;
}

const TH = "px-3 py-1.5 text-right font-normal";
const TD = "px-3 py-1.5 text-right";

export function PositionsTable({ positions, onSelect }: PositionsTableProps) {
  return (
    <Panel title="Positions" aside={<span className="text-xs text-ink-3">{positions.length}</span>}>
      <div className="absolute inset-0 overflow-auto">
        <table data-testid="positions-table" className="w-full text-[13px]">
          <thead className="sticky top-0 bg-panel text-xs text-ink-3">
            <tr className="border-b border-line">
              <th className="px-3 py-1.5 text-left font-normal">Ticker</th>
              <th className={TH}>Qty</th>
              <th className={TH}>Avg cost</th>
              <th className={TH}>Price</th>
              <th className={TH}>Unrealized P&amp;L</th>
              <th className={TH}>Change</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr
                key={p.ticker}
                data-testid={`position-row-${p.ticker}`}
                onClick={() => onSelect(p.ticker)}
                className="cursor-pointer border-b border-line/60 hover:bg-raised"
              >
                <td className="px-3 py-1.5 font-mono font-medium">{p.ticker}</td>
                <td className={TD}>{quantity(p.quantity)}</td>
                <td className={`${TD} text-ink-2`}>{money(p.avg_cost)}</td>
                <td className={TD}>{money(p.current_price)}</td>
                <td className={`${TD} ${trendClass(p.unrealized_pnl)}`}>{signedMoney(p.unrealized_pnl)}</td>
                <td className={`${TD} ${trendClass(p.unrealized_pnl)}`}>
                  {signedPercent(p.unrealized_pnl_percent)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {positions.length === 0 && (
          <p className="p-3 text-sm text-ink-3">No positions yet. Buy shares from the trade bar to start.</p>
        )}
      </div>
    </Panel>
  );
}
