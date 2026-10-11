import { money, signedMoney, trendClass } from "@/lib/format";
import type { Portfolio } from "@/lib/types";
import type { ConnectionStatus } from "@/lib/usePriceStream";

const STATUS: Record<ConnectionStatus, { label: string; dot: string }> = {
  connected: { label: "Live", dot: "bg-up" },
  reconnecting: { label: "Reconnecting", dot: "bg-accent" },
  disconnected: { label: "Disconnected", dot: "bg-down" },
};

export function Header({ portfolio, status }: { portfolio: Portfolio | null; status: ConnectionStatus }) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-8 border-b border-line bg-panel px-4">
      <div className="text-lg font-semibold tracking-tight text-ink">
        Fin<span className="text-accent">Ally</span>
      </div>

      <div className="flex items-baseline gap-2">
        <span className="text-xs text-ink-3">Portfolio</span>
        <span data-testid="header-total-value" className="text-2xl font-semibold text-ink">
          {portfolio ? money(portfolio.total_value) : "--"}
        </span>
      </div>

      <div className="flex items-baseline gap-2">
        <span className="text-xs text-ink-3">Unrealized</span>
        <span className={`text-sm ${portfolio ? trendClass(portfolio.unrealized_pnl) : "text-ink-3"}`}>
          {portfolio ? signedMoney(portfolio.unrealized_pnl) : "--"}
        </span>
      </div>

      <div className="flex items-baseline gap-2">
        <span className="text-xs text-ink-3">Cash</span>
        <span data-testid="header-cash" className="text-sm text-ink">
          {portfolio ? money(portfolio.cash_balance) : "--"}
        </span>
      </div>

      <div
        data-testid="connection-status"
        data-status={status}
        className="ml-auto flex items-center gap-2 text-xs text-ink-2"
        role="status"
      >
        <span className={`h-2 w-2 rounded-full ${STATUS[status].dot}`} aria-hidden />
        {STATUS[status].label}
      </div>
    </header>
  );
}
