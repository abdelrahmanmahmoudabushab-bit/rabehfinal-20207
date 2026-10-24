"use client";

import useSWR, { mutate, type SWRConfiguration } from "swr";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {}
    throw new ApiError(res.status, msg);
  }
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
};

export function useApi<T>(path: string | null, opts?: SWRConfiguration) {
  return useSWR<T>(path, (p: string) => api.get<T>(p), { refreshInterval: 5000, ...opts });
}

/** Revalidate every cached query, e.g. after an approve / kill switch. */
export const refreshAll = () => mutate(() => true);

// ---- types (mirror api/rahbeh/main.py) -----------------------------------------------------
export type Mode = "research" | "copilot" | "autopilot";

export interface Status {
  demo: boolean;
  market_source: string;
  broker: string;
  claude: boolean;
  model: string | null;
  market_open: boolean;
  market_time: string;
  session_rules: boolean;
  last_cycle: string | null;
  last_scan: Record<string, number | string>;
  kill_switch: boolean;
  mode: Mode;
  paused_symbols: string[];
}

export interface Trade {
  id: number;
  proposal_id: number | null;
  symbol: string;
  sector: string;
  qty: number;
  entry_price: number;
  initial_stop: number;
  stop: number;
  target: number;
  opened_at: string;
  closed_at: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  pnl: number | null;
  r_multiple: number | null;
  mode: Mode;
  notes: { at: string; note: string }[];
  price?: number;
  unrealized?: number;
  r_now?: number | null;
  thesis?: string | null;
}

export interface AlertItem {
  id: number;
  at: string;
  level: "info" | "warn" | "critical";
  title: string;
  body: string;
  read: boolean;
}

export interface Dashboard {
  account: { equity: number; cash: number; buying_power: number; day_pnl: number; day_pnl_pct: number };
  positions: Trade[];
  curve: { t: string; equity: number; you: number; sp500: number }[];
  scoreboard: {
    trades: number;
    win_rate: number;
    total_pnl: number;
    avg_win: number;
    avg_loss: number;
    profit_factor: number | null;
    you_pct: number;
    sp500_pct: number;
  };
  pending_proposals: number;
  alerts: AlertItem[];
  unread_alerts: number;
}

export interface Headline {
  headline: string;
  source: string;
  at: string;
  sentiment?: number;
  official?: boolean;
}

export interface RiskCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface Proposal {
  id: number;
  created_at: string;
  symbol: string;
  name: string;
  sector: string;
  score: number;
  entry: number;
  stop: number;
  target: number;
  qty: number;
  risk_amount: number;
  thesis: string;
  analyst: {
    score: number;
    direction: string;
    thesis: string;
    news_view: string;
    chart_view: string;
    company_view: string;
    bullish_points: string[];
    risks: string[];
  };
  devil: { objection: string; severity: number; deal_breaker: boolean; what_would_change_my_mind: string };
  manager: {
    decision: string;
    objection_answered: boolean;
    rebuttal: string;
    confidence: number;
    exit_plan: string;
  };
  features: Record<string, number | string | boolean> & { headlines?: Headline[] };
  risk_checks: RiskCheck[];
  status: "idea" | "pending" | "executed" | "rejected" | "expired" | "blocked";
  status_reason: string | null;
  agent_source: "claude" | "heuristic";
  trade?: Trade | null;
}

export interface LogRow {
  id: number;
  at: string;
  symbol: string | null;
  stage: string;
  outcome: "no" | "yes" | "info" | "alert";
  reason: string;
  detail: Record<string, unknown>;
}

export interface Settings {
  mode: Mode;
  risk_per_trade_pct: number;
  daily_loss_limit_pct: number;
  max_position_pct: number;
  max_sector_pct: number;
  max_open_positions: number;
  max_trades_per_day: number;
  min_reward_risk: number;
  score_threshold: number;
  halal_only: boolean;
  allowed_symbols: string[];
  strategy: string;
  language: "en" | "ar";
  kill_switch: boolean;
  autopilot: { unlocked: boolean; copilot_trades: number; needed: number };
  hard_caps: Record<string, number>;
}

export interface MarketRow {
  symbol: string;
  name: string;
  sector: string;
  price: number;
  change_day_pct: number;
  change_30m_pct: number;
  volume_ratio: number;
  rsi: number;
  trend: "up" | "down" | "flat";
  momentum: number;
  halal: boolean;
  spark: number[];
  paused: boolean;
}

export interface StockDetail {
  symbol: string;
  features: Record<string, number | string | boolean>;
  laya: { sentiment: number; score: number; reasons: string[]; headlines: Headline[]; worth_a_look: boolean };
  company: {
    name: string;
    sector: string;
    industry: string;
    market_cap_b: number;
    revenue_b: number;
    net_margin: number | null;
    debt_to_mcap: number | null;
  } | null;
  halal: { passes: boolean; reasons: string[]; debt_ratio: number | null; cash_ratio: number | null };
  bars: { t: string; c: number; v: number }[];
  news: Headline[];
}

export interface Review {
  id: number;
  at: string;
  day: string;
  stats: {
    trades: number;
    win_rate: number;
    pnl: number;
    avg_r: number;
    targets_hit: number;
    stopped_out: number;
    account_return_pct: number;
    sp500_return_pct: number;
    proposals: number;
  };
  summary: string;
  lessons: string[];
  proposed_change: { score_threshold: number; min_reward_risk: number };
  change_applied: boolean;
  change_verdict: string;
}

export interface Usage {
  calls_24h: number;
  errors_24h: number;
  input_tokens_24h: number;
  output_tokens_24h: number;
  cache_read_tokens_24h: number;
  est_cost_24h: number;
  recent: { at: string; agent: string; symbol: string | null; model: string; in: number; out: number; ms: number; ok: boolean; error: string | null }[];
}
