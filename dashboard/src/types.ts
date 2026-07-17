export type RadarRole =
  | "next_buy"
  | "strong_stock"
  | "golden_pit"
  | "accumulation"
  | "monthly_base"
  | "expectation_gap"
  | "leader_tape"
  | "market_watchlist";

export interface MarketStructure {
  status?: string;
  score?: number;
}

export interface RadarRun {
  run_key: string;
  market_date?: string;
  generated_at?: string;
  mode?: string;
  scanned_symbols?: number;
  top_theme?: string;
  gate_level?: "green" | "yellow" | "red" | string;
  gate_state?: string;
  gate_score?: number;
  summary?: {
    market_structure?: MarketStructure;
  };
}

export interface ThemeSnapshot {
  breadth_5d?: number;
  breadth_20d?: number;
  amount_heat?: number;
  price_phase?: string;
}

export interface ThemeRow {
  run_key: string;
  market_date?: string;
  theme: string;
  rank?: number;
  status?: string;
  score?: number;
  lifecycle_stage?: string;
  snapshot?: ThemeSnapshot;
  lifecycle?: {
    stage?: string;
  };
}

export interface TradePlan {
  decision?: string;
  entry_plan?: string;
  confirmation?: string;
  invalidation?: string;
  position_note?: string;
  action?: string;
}

export interface TargetPayload {
  horizon?: string;
  target_low?: number;
  target_high?: number;
  upside_low?: number;
  reward_risk_low?: number;
  stop_price?: number;
  confidence?: string;
}

export interface FundamentalPayload {
  status?: string;
  score?: number;
  revenue_yoy?: number;
  net_income_yoy?: number;
  roe?: number;
  price_to_book?: number;
}

export interface MarketMetrics {
  ret_5d?: number;
  ret_20d?: number;
  range_position_60d?: number;
  amount_ratio?: number;
  amount_ratio_5_20?: number;
}

export interface StrongStockSignal {
  fundamental_status?: string;
  fundamental_score?: number;
  backtest?: {
    win_rate?: number;
    avg_return?: number;
  };
}

export interface SymbolRow {
  run_key: string;
  market_date?: string;
  symbol: string;
  name?: string;
  primary_theme?: string;
  themes?: string[];
  roles?: RadarRole[];
  action_state?: string;
  priority_score?: number;
  last_close?: number;
  trade_plan?: TradePlan;
  target_payload?: TargetPayload;
  fundamental_payload?: FundamentalPayload;
  market_metrics?: MarketMetrics;
  signal_payload?: {
    strong_stock?: StrongStockSignal;
  };
}

export interface DashboardData {
  schema_version: string;
  built_at?: string;
  current_run_key?: string;
  runs: RadarRun[];
  themes: ThemeRow[];
  symbols: SymbolRow[];
}
