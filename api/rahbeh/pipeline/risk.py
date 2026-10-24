"""The risk engine — plain code with the final say. No agent output can bypass it.

User settings are clamped to HARD_* caps here, so even a bad settings write or a confused
agent cannot raise risk past them.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, time
from zoneinfo import ZoneInfo

from ..broker.base import Account, Position

HARD_MAX_RISK_PER_TRADE_PCT = 1.0  # "1% risk max per trade"
HARD_MAX_DAILY_LOSS_PCT = 5.0
HARD_MAX_POSITION_PCT = 25.0
HARD_MAX_SECTOR_PCT = 50.0
HARD_MAX_OPEN_POSITIONS = 10
HARD_MIN_REWARD_RISK = 1.0
MIN_STOP_DISTANCE_PCT = 0.15
MAX_STOP_DISTANCE_PCT = 8.0
LAST_ENTRY_ET = time(15, 30)
FLATTEN_ET = time(15, 50)
FIRST_ENTRY_ET = time(9, 35)  # skip the opening auction chaos

ET = ZoneInfo("America/New_York")


@dataclass
class Limits:
    risk_per_trade_pct: float
    daily_loss_limit_pct: float
    max_position_pct: float
    max_sector_pct: float
    max_open_positions: int
    max_trades_per_day: int
    min_reward_risk: float
    allowed_symbols: list[str] = field(default_factory=list)

    def clamped(self) -> "Limits":
        return Limits(
            risk_per_trade_pct=min(max(self.risk_per_trade_pct, 0.05), HARD_MAX_RISK_PER_TRADE_PCT),
            daily_loss_limit_pct=min(max(self.daily_loss_limit_pct, 0.25), HARD_MAX_DAILY_LOSS_PCT),
            max_position_pct=min(max(self.max_position_pct, 1), HARD_MAX_POSITION_PCT),
            max_sector_pct=min(max(self.max_sector_pct, 5), HARD_MAX_SECTOR_PCT),
            max_open_positions=min(max(self.max_open_positions, 1), HARD_MAX_OPEN_POSITIONS),
            max_trades_per_day=max(self.max_trades_per_day, 1),
            min_reward_risk=max(self.min_reward_risk, HARD_MIN_REWARD_RISK),
            allowed_symbols=[s.upper() for s in self.allowed_symbols],
        )


@dataclass
class TradeRequest:
    symbol: str
    sector: str
    entry: float
    stop: float
    target: float


@dataclass
class RiskContext:
    account: Account
    positions: list[Position]
    sector_of: dict[str, str]
    realized_pnl_today: float
    trades_today: int
    kill_switch: bool
    now: datetime
    session_rules: bool = True  # off for the always-open demo market


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class RiskDecision:
    approved: bool
    qty: int
    risk_amount: float
    checks: list[Check]

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    @property
    def reason(self) -> str:
        return "; ".join(c.detail for c in self.failed) or "all checks passed"

    def as_list(self) -> list[dict]:
        return [c.__dict__ for c in self.checks]


def day_pnl(ctx: RiskContext) -> float:
    return ctx.account.equity - ctx.account.last_equity


def daily_loss_hit(ctx: RiskContext, limits: Limits) -> bool:
    lim = limits.clamped()
    return day_pnl(ctx) <= -ctx.account.last_equity * lim.daily_loss_limit_pct / 100


def evaluate(req: TradeRequest, ctx: RiskContext, limits: Limits) -> RiskDecision:
    lim = limits.clamped()
    checks: list[Check] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append(Check(name, bool(ok), detail))

    add("kill_switch", not ctx.kill_switch, "kill switch is on" if ctx.kill_switch else "kill switch off")

    if ctx.session_rules:
        et = ctx.now.astimezone(ET).time()
        add("session", FIRST_ENTRY_ET <= et <= LAST_ENTRY_ET,
            f"new trades allowed {FIRST_ENTRY_ET:%H:%M}–{LAST_ENTRY_ET:%H:%M} ET (now {et:%H:%M})")

    hit = daily_loss_hit(ctx, lim)
    add("daily_loss", not hit, f"today's P&L {day_pnl(ctx):+,.2f} vs limit -{lim.daily_loss_limit_pct}%")

    add("trades_today", ctx.trades_today < lim.max_trades_per_day, f"{ctx.trades_today}/{lim.max_trades_per_day} trades today")

    if lim.allowed_symbols:
        add("allowed_list", req.symbol in lim.allowed_symbols, f"{req.symbol} {'is' if req.symbol in lim.allowed_symbols else 'is not'} on your allowed list")

    held = {p.symbol for p in ctx.positions}
    add("not_held", req.symbol not in held, "already holding" if req.symbol in held else "not already held")
    add("open_positions", len(ctx.positions) < lim.max_open_positions, f"{len(ctx.positions)}/{lim.max_open_positions} open positions")

    # Price sanity: long only — stop below entry, target above
    per_share_risk = req.entry - req.stop
    stop_pct = per_share_risk / req.entry * 100 if req.entry else 0
    shape_ok = req.stop < req.entry < req.target
    add("order_shape", shape_ok, f"stop {req.stop:.2f} < entry {req.entry:.2f} < target {req.target:.2f}")
    add("stop_distance", MIN_STOP_DISTANCE_PCT <= stop_pct <= MAX_STOP_DISTANCE_PCT,
        f"stop is {stop_pct:.2f}% away (allowed {MIN_STOP_DISTANCE_PCT}–{MAX_STOP_DISTANCE_PCT}%)")
    rr = (req.target - req.entry) / per_share_risk if per_share_risk > 0 else 0
    add("reward_risk", rr >= lim.min_reward_risk, f"reward/risk {rr:.2f} (min {lim.min_reward_risk})")

    # Sizing: risk at most X% of equity, then cap by position size, sector exposure and cash
    equity = ctx.account.equity
    qty = 0
    if shape_ok and per_share_risk > 0:
        qty = math.floor(equity * lim.risk_per_trade_pct / 100 / per_share_risk)
        qty = min(qty, math.floor(equity * lim.max_position_pct / 100 / req.entry))
        sector_value = sum(p.market_value for p in ctx.positions if ctx.sector_of.get(p.symbol) == req.sector)
        sector_room = equity * lim.max_sector_pct / 100 - sector_value
        qty = min(qty, math.floor(max(sector_room, 0) / req.entry))
        qty = min(qty, math.floor(ctx.account.buying_power * 0.98 / req.entry))
        add("sector_exposure", sector_room > req.entry,
            f"{req.sector} exposure {sector_value / equity:.0%} of equity (limit {lim.max_sector_pct}%)" if equity else "no equity")
    add("size", qty >= 1, f"{qty} shares, risking {qty * per_share_risk:,.2f} ({lim.risk_per_trade_pct}% max)")

    approved = all(c.passed for c in checks)
    return RiskDecision(approved, qty if approved else 0, round(qty * max(per_share_risk, 0), 2), checks)


def should_flatten(now: datetime, session_rules: bool) -> bool:
    return session_rules and now.astimezone(ET).time() >= FLATTEN_ET


def trail_stop(entry: float, initial_stop: float, current_stop: float, price: float) -> float:
    """Raise the stop as the trade works: breakeven at +1R, lock in +1R at +2R, then trail 1R behind."""
    r = entry - initial_stop
    if r <= 0:
        return current_stop
    gained = (price - entry) / r
    new = current_stop
    if gained >= 1:
        new = max(new, entry)
    if gained >= 2:
        new = max(new, price - r)
    return round(new, 2)
