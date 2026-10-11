export interface PriceUpdate {
  ticker: string;
  price: number;
  previous_price: number;
  prev_close: number;
  change: number;
  day_change_percent: number;
  direction: "up" | "down" | "flat";
  timestamp: number;
}

export type PriceMap = Record<string, PriceUpdate>;

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
}

export interface Portfolio {
  cash_balance: number;
  positions_value: number;
  total_value: number;
  unrealized_pnl: number;
  positions: Position[];
}

export type Side = "buy" | "sell";

export interface Trade {
  id: string;
  ticker: string;
  side: Side;
  quantity: number;
  price: number;
  executed_at: string;
}

export interface Snapshot {
  total_value: number;
  recorded_at: string;
}

export interface WatchlistEntry {
  ticker: string;
  added_at: string;
  quote: PriceUpdate | null;
}

export interface TradeAction {
  ticker: string;
  side: Side;
  quantity: number;
  status: "executed" | "failed";
  price: number | null;
  error: string | null;
}

export interface WatchlistAction {
  ticker: string;
  action: "add" | "remove";
  status: "executed" | "failed";
  error: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  actions: { trades: TradeAction[]; watchlist_changes: WatchlistAction[] } | null;
  created_at: string;
}
