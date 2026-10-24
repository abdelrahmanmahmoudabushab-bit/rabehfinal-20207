"""Skills: the read-only tools an agent can call. Each skill is backed by one data source / API.

With Claude, an agent gets its own skills as tools and decides what to look up. Without Claude, the
rule-based version of the agent calls the same skills directly, so either way you can see exactly
which data each agent used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from ..market.base import TIMEFRAMES
from ..market.universe import BENCHMARK, sector_of
from ..pipeline import features, halal, laya, risk

if TYPE_CHECKING:
    from ..engine import Engine


@dataclass
class Skill:
    name: str
    description: str
    sources: list[str]  # which APIs / data sources back it (shown in the UI)
    params: dict  # JSON schema "properties"
    required: list[str]
    fn: Callable[..., Any]

    def tool(self) -> dict:
        return {
            "name": self.name,
            "description": f"{self.description} (data: {', '.join(self.sources)})",
            "input_schema": {"type": "object", "properties": self.params, "required": self.required, "additionalProperties": False},
        }


SYM = {"symbol": {"type": "string", "description": "US stock ticker, e.g. AAPL"}}


def _features(e: Engine, symbol: str) -> dict:
    bars = e.market.minute_bars(symbol, 240)
    if len(bars) < 2:
        raise ValueError(f"no price data for {symbol}")
    return features.compute(bars, e.market.daily_bars(symbol, 60)).to_dict()


def scan_market(e: Engine, limit: int = 10) -> list[dict]:
    """Rank every stock in the universe by a blend of momentum, volume, news tone and trend."""
    news = e.market.news(None, 100)
    now = e.market.now()
    rows = []
    for sym in e.market.universe():
        bars = e.market.minute_bars(sym, 240)
        if len(bars) < 30:
            continue
        f = features.compute(bars, e.market.daily_bars(sym, 60))
        lr = laya.evaluate(sym, f, news, now)
        rows.append({"symbol": sym, "score": lr.score, "worth_a_look": lr.worth_a_look, "price": round(f.price, 2),
                     "change_day_pct": round(f.change_day_pct, 2), "change_30m_pct": round(f.change_30m_pct, 2),
                     "volume_ratio": round(f.volume_ratio, 2), "rsi": round(f.rsi14, 1), "trend": f.trend,
                     "news_sentiment": lr.sentiment, "reasons": lr.reasons})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[: max(1, min(limit, 30))]


def get_quote(e: Engine, symbol: str) -> dict:
    q = e.market.quote(symbol)
    second = e.market.second_quote(symbol)
    return {"symbol": symbol, "price": q.price if q else None, "as_of": q.ts.isoformat() if q else None,
            "source": q.source if q else None, "second_source_price": second.price if second else None}


def get_indicators(e: Engine, symbol: str) -> dict:
    return {"symbol": symbol, **_features(e, symbol)}


def get_candles(e: Engine, symbol: str, timeframe: str = "5m", limit: int = 60) -> dict:
    tf = timeframe if timeframe in TIMEFRAMES else "5m"
    bars = e.market.history(symbol, tf, max(5, min(limit, 120)))
    return {"symbol": symbol, "timeframe": tf, "candles": [
        {"t": b.ts.isoformat(), "o": round(b.o, 2), "h": round(b.h, 2), "l": round(b.l, 2), "c": round(b.c, 2), "v": round(b.v)} for b in bars]}


def get_headlines(e: Engine, symbol: str) -> dict:
    f = features.compute(e.market.minute_bars(symbol, 240), e.market.daily_bars(symbol, 60))
    lr = laya.evaluate(symbol, f, e.market.news([symbol], 30), e.market.now(), lookback_min=24 * 60)
    return {"symbol": symbol, "headlines": lr.headlines, "average_sentiment": lr.sentiment}


def get_filings(e: Engine, symbol: str) -> dict:
    return {"symbol": symbol, "filings": [vars(x) for x in e.extras.filings(symbol, 8)]}


def get_fundamentals(e: Engine, symbol: str) -> dict:
    fd = e.market.fundamentals(symbol)
    if not fd:
        return {"symbol": symbol, "error": "no company data"}
    return {"symbol": symbol, "name": fd.name, "sector": fd.sector, "industry": fd.industry,
            "market_cap_b": round(fd.market_cap / 1e9, 1), "revenue_b": round(fd.revenue / 1e9, 1),
            "net_margin": round(fd.net_income / fd.revenue, 3) if fd.revenue else None,
            "debt_to_mcap": round(fd.total_debt / fd.market_cap, 3) if fd.market_cap else None,
            "cash_to_mcap": round(fd.cash / fd.market_cap, 3) if fd.market_cap else None}


def get_earnings(e: Engine, symbol: str) -> dict:
    return {"symbol": symbol, **e.earnings_ctx(symbol)}


def get_analyst_ratings(e: Engine, symbol: str) -> dict:
    return {"symbol": symbol, "ratings": e.ratings_ctx(symbol)}


def get_market_mood(e: Engine) -> dict:
    if e.mood is None:
        e.update_mood()
    m = e.mood.to_dict() if e.mood else {}
    m.pop("events", None)
    return m


def get_economic_calendar(e: Engine) -> dict:
    return {"events": e.mood.events if e.mood else [vars(x) for x in e.extras.mood_inputs().events]}


def get_benchmark(e: Engine) -> dict:
    return {"symbol": BENCHMARK, **_features(e, BENCHMARK)}


def check_halal(e: Engine, symbol: str) -> dict:
    h = halal.screen(e.market.fundamentals(symbol))
    return {"symbol": symbol, "passes": h.passes, "reasons": h.reasons, "debt_ratio": h.debt_ratio, "cash_ratio": h.cash_ratio}


def get_account(e: Engine) -> dict:
    a = e.broker.account()
    return {"equity": round(a.equity, 2), "cash": round(a.cash, 2), "buying_power": round(a.buying_power, 2),
            "day_pnl": round(a.equity - a.last_equity, 2),
            "positions": [{"symbol": p.symbol, "qty": p.qty, "avg_price": p.avg_price, "price": p.market_price} for p in e.broker.positions()]}


def get_position(e: Engine, symbol: str) -> dict:
    from ..db import SessionLocal, Trade
    from sqlalchemy import select

    with SessionLocal() as db:
        t = db.scalar(select(Trade).where(Trade.symbol == symbol, Trade.closed_at.is_(None)))
        if not t:
            return {"symbol": symbol, "open": False}
        q = e.market.quote(symbol)
        price = q.price if q else t.entry_price
        r = t.entry_price - t.initial_stop
        return {"symbol": symbol, "open": True, "qty": t.qty, "entry": t.entry_price, "stop": t.stop, "initial_stop": t.initial_stop,
                "target": t.target, "price": price, "unrealized": round((price - t.entry_price) * t.qty, 2),
                "r_multiple": round((price - t.entry_price) / r, 2) if r > 0 else None, "opened_at": t.opened_at.isoformat(),
                "notes": t.notes[-5:]}


def risk_check(e: Engine, symbol: str, entry: float, stop: float, target: float) -> dict:
    """Dry run of the plain-code risk engine: would this plan be allowed, and at what size?"""
    from ..db import SessionLocal

    with SessionLocal() as db:
        u = e.settings_row(db)
        rd = risk.evaluate(risk.TradeRequest(symbol, sector_of(symbol), entry, stop, target, e.earnings_ctx(symbol)["days_until"]),
                           e.risk_context(db, u), e.limits(u))
    return {"approved": rd.approved, "max_qty": rd.qty, "risk_amount": rd.risk_amount, "failed": [c.detail for c in rd.failed]}


def run_backtest(e: Engine, symbol: str) -> dict:
    """Test the setup firing on this stock right now 1,000+ ways on history (out-of-sample)."""
    r = e.backtest_trade(symbol)
    best = r.get("best") or {}
    return {"symbol": symbol, "verdict": r.get("verdict"), "setup": r.get("setup"), "variants_tested": r.get("variants_tested"),
            "best_variant": best.get("key"), "in_sample": best.get("is"), "out_of_sample": best.get("oos"),
            "share_of_variants_profitable_oos": r.get("share_oos_positive"), "monte_carlo_p_loss": (r.get("monte_carlo") or {}).get("p_loss"),
            "tuned_plan": r.get("tuned_plan"), "reasons": r.get("reasons")}


def get_recent_trades(e: Engine, limit: int = 20) -> dict:
    from ..db import SessionLocal, Trade
    from sqlalchemy import select

    with SessionLocal() as db:
        rows = db.scalars(select(Trade).where(Trade.closed_at.is_not(None)).order_by(Trade.id.desc()).limit(min(limit, 50))).all()
        return {"trades": [{"symbol": t.symbol, "entry": t.entry_price, "exit": t.exit_price, "reason": t.exit_reason,
                            "pnl": t.pnl, "r": t.r_multiple} for t in rows]}


def get_decision_log(e: Engine, limit: int = 30) -> dict:
    from ..db import DecisionLog, SessionLocal
    from sqlalchemy import select

    with SessionLocal() as db:
        rows = db.scalars(select(DecisionLog).where(DecisionLog.stage != "laya").order_by(DecisionLog.id.desc()).limit(min(limit, 60))).all()
        return {"entries": [{"at": r.at.isoformat(), "symbol": r.symbol, "stage": r.stage, "outcome": r.outcome, "reason": r.reason[:200]} for r in rows]}


SKILLS: dict[str, Skill] = {s.name: s for s in [
    Skill("scan_market", "Rank the whole stock universe by momentum, volume, news tone and trend", ["Alpaca market data", "Alpaca news"],
          {"limit": {"type": "integer", "description": "how many top stocks to return (max 30)"}}, [], scan_market),
    Skill("get_quote", "Latest price from the broker feed and the second price source", ["Alpaca market data", "Finnhub"], SYM, ["symbol"], get_quote),
    Skill("get_indicators", "Trend, VWAP, EMA 9/21, RSI 14, ATR, relative volume, day range, 20-day trend", ["Alpaca market data"],
          SYM, ["symbol"], get_indicators),
    Skill("get_candles", "OHLCV candles (1m, 5m, 15m, 1h, 1D)", ["Alpaca market data"],
          {**SYM, "timeframe": {"type": "string", "enum": list(TIMEFRAMES)}, "limit": {"type": "integer"}}, ["symbol"], get_candles),
    Skill("get_headlines", "Recent headlines for a stock with publish time and tone", ["Alpaca news"], SYM, ["symbol"], get_headlines),
    Skill("get_filings", "Recent SEC filings (8-K, 10-Q, 10-K, insider Form 4, 13D/G)", ["SEC EDGAR"], SYM, ["symbol"], get_filings),
    Skill("get_fundamentals", "Sector, market value, revenue, margin, debt and cash", ["Financial Modeling Prep"], SYM, ["symbol"], get_fundamentals),
    Skill("get_earnings", "Next earnings date and the last four EPS surprises", ["Finnhub"], SYM, ["symbol"], get_earnings),
    Skill("get_analyst_ratings", "Latest analyst buy/hold/sell counts", ["Finnhub"], SYM, ["symbol"], get_analyst_ratings),
    Skill("get_market_mood", "VIX, Fed funds, 10-year yield, oil, S&P 500 move, breadth and the mood level", ["FRED", "Alpaca market data"], {}, [], get_market_mood),
    Skill("get_economic_calendar", "Today's and tomorrow's economic events with impact", ["Finnhub", "Financial Modeling Prep"], {}, [], get_economic_calendar),
    Skill("get_benchmark", "S&P 500 (SPY) indicators", ["Alpaca market data"], {}, [], get_benchmark),
    Skill("check_halal", "Business-activity and AAOIFI ratio screen", ["Financial Modeling Prep"], SYM, ["symbol"], check_halal),
    Skill("get_account", "Equity, cash, today's P&L and open positions", ["Alpaca broker"], {}, [], get_account),
    Skill("get_position", "Our open position in a stock: size, entry, stop, target, P&L in R", ["Rahbeh database", "Alpaca broker"], SYM, ["symbol"], get_position),
    Skill("risk_check", "Dry-run the risk engine on a plan: allowed or not, and the maximum size", ["Rahbeh risk engine"],
          {**SYM, "entry": {"type": "number"}, "stop": {"type": "number"}, "target": {"type": "number"}}, ["symbol", "entry", "stop", "target"], risk_check),
    Skill("run_backtest", "Backtest the setup firing on a stock right now, 1,000+ ways, judged out of sample with Monte Carlo",
          ["Alpaca market data", "Rahbeh backtester"], SYM, ["symbol"], run_backtest),
    Skill("get_recent_trades", "Recently closed trades with result and R multiple", ["Rahbeh database"],
          {"limit": {"type": "integer"}}, [], get_recent_trades),
    Skill("get_decision_log", "Recent decisions and every 'no' with its reason", ["Rahbeh database"],
          {"limit": {"type": "integer"}}, [], get_decision_log),
]}


def call(e: Engine, name: str, args: dict) -> tuple[Any, str]:
    """Run one skill; returns (result, short summary for the trace). Errors come back as data, never raise."""
    skill = SKILLS.get(name)
    if not skill:
        return {"error": f"unknown skill {name}"}, "unknown skill"
    try:
        args = {k: v for k, v in (args or {}).items() if k in skill.params}
        if "symbol" in args:
            args["symbol"] = str(args["symbol"]).upper()
        out = skill.fn(e, **args)
    except Exception as err:  # the agent sees the error and can recover
        return {"error": str(err)}, f"error: {err}"
    return out, _summary(name, out)


def _summary(name: str, out: Any) -> str:
    if isinstance(out, list):
        return f"{len(out)} rows"
    if not isinstance(out, dict):
        return ""
    for key in ("headlines", "filings", "candles", "trades", "entries", "events"):
        if key in out and isinstance(out[key], list):
            return f"{len(out[key])} {key}"
    if name == "risk_check":
        return "allowed" if out.get("approved") else "blocked: " + "; ".join(out.get("failed", []))[:120]
    text = json.dumps(out, default=str)
    return text[:120] + ("…" if len(text) > 120 else "")
