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
  origin?: string;
  peak_price?: number | null;
  keeper_log?: KeeperEntry[];
  plan?: { max_hold_min?: number | null; trail?: string; expected_r?: number; variant?: string; setup?: string };
}

export interface SkillUse {
  skill: string;
  args?: Record<string, unknown>;
  summary: string;
}

export interface KeeperEntry {
  at: string;
  action: "hold" | "tighten" | "sell";
  reason: string;
  confidence: number;
  by: string;
  price: number | null;
  r: number;
  new_stop?: number;
  checks?: number;
  skills: SkillUse[];
}

export interface HuntStep {
  at: string;
  agent: string;
  symbol: string | null;
  text: string;
  by: string;
  skills: SkillUse[];
  ok: boolean | null;
}

export interface Hunt {
  id: string;
  started_at: string;
  status: "running" | "found" | "no_deal" | "failed" | "bought";
  steps: HuntStep[];
  ranking: { symbol: string; score: number; price: number; change_day_pct: number; volume_ratio: number; trend: string; news_sentiment: number }[];
  candidates: { symbol: string; name: string; score: number; direction: string; thesis: string; price: number; change_day_pct: number }[];
  deal: {
    symbol: string;
    name: string;
    score: number;
    thesis: string;
    entry: number;
    stop: number;
    target: number;
    max_qty: number;
    risk_per_share: number;
    reward_per_share: number;
    exit_plan: string;
    devil: Proposal["devil"];
    manager: Proposal["manager"];
    team: TeamReports;
    risk_checks: RiskCheck[];
    mood: string;
    backtest?: Backtest;
    tuned_by_backtest?: boolean;
    manager_levels?: { entry: number; stop: number; target: number };
  } | null;
  proposal_id: number | null;
  trade_id: number | null;
  trade?: Trade;
  finished_at: string | null;
  message: string;
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
  team: TeamReports;
  backtest?: Backtest;
  trade?: Trade | null;
}

export interface TeamReports {
  news?: { sentiment: number; company_specific: boolean; priced_in: boolean; key_points: string[]; summary: string; by: string };
  chart?: { trend: string; setup: string; support: number; resistance: number; strength: number; summary: string; by: string };
  company?: { health: string; earnings_risk: boolean; analyst_view: string; red_flags: string[]; summary: string; by: string };
  mood?: { level?: string; summary: string; watch_out_for: string[]; by: string };
}

export interface MacroEvent {
  time: string;
  country: string;
  event: string;
  impact: "high" | "medium" | "low";
}

export interface Mood {
  level: "calm" | "careful" | "stormy";
  risk_multiplier: number;
  reasons: string[];
  spy_change_pct: number;
  breadth_pct: number;
  vix: number | null;
  vix_change: number | null;
  fed_funds: number | null;
  ten_year: number | null;
  ten_year_change_bp: number | null;
  oil: number | null;
  oil_change_pct: number | null;
  events: MacroEvent[];
  next_event: MacroEvent | null;
  summary: string;
  source: string;
  report: { summary: string; watch_out_for: string[]; by: string };
}

export interface AgentInfo {
  id: string;
  name: string;
  kind: "claude" | "rules" | "code";
  when: string;
  plan_no: number | null;
  job: string;
  reads: string[];
  writes: string;
  module?: string;
  apis: string[];
  skills: { name: string; description: string; sources: string[] }[];
  calls_24h: number;
  errors_24h: number;
  avg_ms: number | null;
  tokens_24h: number;
}

export interface AgentsOverview {
  team_mode: string;
  claude: boolean;
  model: string | null;
  agents: AgentInfo[];
  skills: { name: string; description: string; sources: string[]; calls_24h: number; used_by: string[] }[];
  runs: Proposal[];
}

export interface Source {
  name: string;
  provides: string;
  status: "connected" | "simulated" | "missing_key" | "not_wired";
  env: string;
  note: string;
}

export interface Earnings {
  next_date: string | null;
  next_hour: string | null;
  eps_estimate: number | null;
  days_until: number | null;
  history: { period: string; estimate: number | null; actual: number | null; surprise_pct: number | null }[];
}

export interface Ratings {
  period: string;
  strong_buy: number;
  buy: number;
  hold: number;
  sell: number;
  strong_sell: number;
  total: number;
  score: number | null;
}

export interface Filing {
  form: string;
  filed: string;
  description: string;
  url: string;
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
  earnings: Earnings;
  ratings: Ratings | null;
  filings: Filing[];
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
  trades_24h: number;
  cost_per_trade: number | null;
  budget_usd: number;
  spend_today: number;
  over_budget: boolean;
  calls_24h: number;
  errors_24h: number;
  input_tokens_24h: number;
  output_tokens_24h: number;
  cache_read_tokens_24h: number;
  cache_saved_24h?: number;
  est_cost_24h: number;
  recent: { at: string; agent: string; symbol: string | null; model: string; in: number; out: number; ms: number; ok: boolean; error: string | null }[];
}

export interface Analysis {
  symbol: string;
  source: "claude" | "heuristic";
  verdict: "trade" | "no trade";
  gates: { name: string; passed: boolean; detail: string }[];
  analyst: Proposal["analyst"];
  devil: Proposal["devil"];
  manager: Proposal["manager"];
  plan: { entry: number; stop: number; target: number; qty: number; risk_amount: number };
  risk_checks: RiskCheck[];
  proposal_id: number | null;
  team: TeamReports;
  backtest?: Backtest;
}

export interface CandlesResponse {
  symbol: string;
  tf: string;
  bars: { time: number; open: number; high: number; low: number; close: number; volume: number }[];
  trades: Trade[];
  last: number;
}

export interface BtStats {
  n: number;
  win: number;
  exp_r: number;
  pf: number;
  mdd_r: number;
  t: number;
  avg_pct: number;
}

export interface BtRow {
  key: string;
  variant: { setup: string; min_rvol: number; rsi_cap: number; stop_atr: number; target_r: number; trail: string; max_hold: number };
  applicable: boolean;
  is: BtStats;
  oos: BtStats;
}

export interface Backtest {
  verdict: "edge" | "no_edge" | "not_enough_data" | "error";
  reasons: string[];
  variants_tested: number;
  symbols?: string[];
  setups?: string[];
  bars?: number;
  days?: number;
  signals?: number;
  split_at?: number;
  slip_bps?: number;
  best?: BtRow | null;
  leaderboard?: BtRow[];
  share_oos_positive?: number;
  median_oos_exp_r?: number;
  is_oos_rank_corr?: number;
  heatmap?: { stops: number[]; targets: number[]; cells: number[][] };
  setup_summary?: { setup: string; signals: number; description: string; share_oos_positive: number; best_oos_exp_r: number }[];
  equity?: { t: number; cum_r: number; oos: boolean }[];
  monte_carlo?: { runs: number; p_loss?: number; median_total_r?: number; p5_total_r?: number; p95_total_r?: number; median_mdd_r?: number; p95_mdd_r?: number; hist?: number[]; hist_edges?: number[] };
  setup?: string;
  setup_description?: string;
  live?: { rvol: number; rsi: number; atr: number; price: number };
  note?: string | null;
  basket?: string[];
  ms?: number;
  source?: string;
  regime?: { current: "trending" | "choppy" | null; by_regime: Record<string, { n: number; exp_r: number; win: number }> };
  selection?: { candidates?: number; oos_t?: number; t_bar?: number; is_t?: number; luck_bar?: number };
  tuned_plan?: { entry: number; stop: number; target: number; max_hold_min: number | null; trail: string; expected_r: number; variant: string };
}

export interface LabJob {
  id: string;
  status: "running" | "done" | "failed";
  started_at: string;
  finished_at?: string;
  progress: string;
  symbols: string[];
  setups: string[];
  days: number;
  result?: Backtest;
  error?: string;
}

export interface AbResult {
  samples: number;
  pending: number;
  min_samples: number;
  agreement: number | null;
  note: string;
  claude: { go: number; no: number; avg_fwd60_go: number | null; avg_fwd60_no: number | null; hit_rate_go: number | null; edge: number | null };
  rules: { go: number; no: number; avg_fwd60_go: number | null; avg_fwd60_no: number | null; hit_rate_go: number | null; edge: number | null };
}

export interface LiveVsBacktest {
  overall: { trades: number; expected_r?: number; realized_r?: number };
  by_setup: Record<string, { trades: number; expected_r: number; realized_r: number }>;
  untested_trades: number;
}

export interface AgentReport {
  days: number;
  agents: { agent: string; calls: number; errors: number; cost: number; avg_ms: number; models: string[] }[];
  blocked_by: { stage: string; count: number }[];
  closed_trades: number;
  by_analyst_score: { bucket: string; trades: number; avg_r: number | null }[];
  by_devil_severity: { bucket: string; trades: number; avg_r: number | null }[];
  note: string;
}

export interface SetupHealth {
  setups: Record<string, { trades: number; live_r: number; expected_r: number | null; status: "ok" | "cut" | "paused"; multiplier: number }>;
  regime: "trending" | "choppy" | null;
}

export interface PrecomputeStatus {
  status?: "running" | "done" | "failed";
  done?: number;
  total?: number;
  regime: "trending" | "choppy" | null;
  cached_verdicts: number;
  workers: number;
  scheduled: boolean;
  seconds?: number;
  note?: string;
  error?: string;
}
