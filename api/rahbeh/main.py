"""FastAPI app: REST API for the web app, plus the in-process scheduler that runs the market cycle."""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .config import get_settings
from .db import AgentCall, Alert, DecisionLog, EquitySnapshot, Proposal, Review, SessionLocal, Trade, UserSettings, init_db
from .engine import Engine
from .market.universe import FUNDAMENTALS, sector_of
from .pipeline import features, halal, risk
from .pipeline.agents import Agents
from .team import hunter
from .team.registry import AGENTS
from .team.skills import SKILLS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rahbeh")
settings = get_settings()

# $ per million tokens (input, output) for the usage estimate
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50), "claude-fable-5-1": (10.0, 50.0)}
AUTOPILOT_UNLOCK_TRADES = 5 if settings.demo else 20

engine: Engine | None = None
scheduler = BackgroundScheduler(timezone="UTC")


def build_engine() -> Engine:
    if settings.demo:
        from .broker.sim import SimBroker
        from .market.sim import SimMarket

        market = SimMarket(always_open=settings.demo_always_open)
        broker = SimBroker(market)
    else:
        from .broker.alpaca_broker import AlpacaBroker
        from .market.live import LiveMarket

        market = LiveMarket(settings)
        market.refresh()
        broker = AlpacaBroker(settings)
    return Engine(settings, market, broker, Agents(settings))


def _demo_restart_cleanup(e: Engine) -> None:
    """The demo broker keeps positions in memory, so trades left open by a restart are closed flat."""
    with SessionLocal() as db:
        for t in e.open_trades(db):
            t.closed_at, t.exit_price, t.exit_reason, t.pnl, t.r_multiple = e.market.now(), t.entry_price, "demo restart", 0.0, 0.0
        for p in db.scalars(select(Proposal).where(Proposal.status.in_(["pending", "idea"]))).all():
            p.status, p.status_reason = "expired", "demo restart"
        db.commit()


def _safe_cycle() -> None:
    try:
        summary = E().cycle()
        log.info("cycle: %s", summary)
    except Exception:
        log.exception("cycle failed")


def _safe_review() -> None:
    try:
        E().review()
    except Exception:
        log.exception("review failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global engine
    init_db()
    engine = build_engine()
    if settings.demo:
        _demo_restart_cleanup(engine)
    scheduler.add_job(_safe_cycle, "interval", seconds=settings.scan_interval_seconds, max_instances=1, coalesce=True,
                      next_run_time=datetime.now(UTC) + timedelta(seconds=3))
    scheduler.add_job(_safe_review, CronTrigger(hour=16, minute=30, timezone="America/New_York"))
    scheduler.start()
    log.info("Rahbeh started (demo=%s, claude=%s)", settings.demo, settings.claude_enabled)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Rahbeh API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])


def E() -> Engine:
    if engine is None:
        raise HTTPException(503, "engine starting")
    return engine


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


# ---- serializers -------------------------------------------------------------------------
def proposal_out(p: Proposal) -> dict:
    return {
        "id": p.id, "created_at": iso(p.created_at), "symbol": p.symbol, "score": p.score, "entry": p.entry,
        "stop": p.stop, "target": p.target, "qty": p.qty, "risk_amount": p.risk_amount, "thesis": p.thesis,
        "analyst": p.analyst, "devil": p.devil, "manager": p.manager, "features": p.features,
        "risk_checks": p.risk_checks, "status": p.status, "status_reason": p.status_reason,
        "agent_source": p.agent_source, "sector": sector_of(p.symbol), "team": p.team or {},
        "name": FUNDAMENTALS[p.symbol].name if p.symbol in FUNDAMENTALS else p.symbol,
    }


def trade_out(t: Trade, price: float | None = None) -> dict:
    d = {
        "id": t.id, "proposal_id": t.proposal_id, "symbol": t.symbol, "sector": t.sector, "qty": t.qty,
        "entry_price": t.entry_price, "initial_stop": t.initial_stop, "stop": t.stop, "target": t.target,
        "opened_at": iso(t.opened_at), "closed_at": iso(t.closed_at), "exit_price": t.exit_price,
        "exit_reason": t.exit_reason, "pnl": t.pnl, "r_multiple": t.r_multiple, "mode": t.mode, "notes": t.notes,
        "origin": t.origin, "peak_price": t.peak_price, "keeper_log": t.keeper_log or [],
    }
    if price is not None and t.closed_at is None:
        d["price"] = price
        d["unrealized"] = round((price - t.entry_price) * t.qty, 2)
        r = t.entry_price - t.initial_stop
        d["r_now"] = round((price - t.entry_price) / r, 2) if r > 0 else None
    return d


def settings_out(u: UserSettings, db) -> dict:
    copilot_trades = db.scalar(select(func.count(Trade.id)).where(Trade.closed_at.is_not(None), Trade.mode == "copilot")) or 0
    return {
        "mode": u.mode, "risk_per_trade_pct": u.risk_per_trade_pct, "daily_loss_limit_pct": u.daily_loss_limit_pct,
        "max_position_pct": u.max_position_pct, "max_sector_pct": u.max_sector_pct, "max_open_positions": u.max_open_positions,
        "max_trades_per_day": u.max_trades_per_day, "min_reward_risk": u.min_reward_risk, "score_threshold": u.score_threshold,
        "halal_only": u.halal_only, "allowed_symbols": u.allowed_symbols, "strategy": u.strategy, "language": u.language,
        "kill_switch": u.kill_switch,
        "autopilot": {"unlocked": u.autopilot_unlocked or copilot_trades >= AUTOPILOT_UNLOCK_TRADES,
                      "copilot_trades": copilot_trades, "needed": AUTOPILOT_UNLOCK_TRADES},
        "hard_caps": {"risk_per_trade_pct": risk.HARD_MAX_RISK_PER_TRADE_PCT, "daily_loss_limit_pct": risk.HARD_MAX_DAILY_LOSS_PCT,
                      "max_position_pct": risk.HARD_MAX_POSITION_PCT, "max_sector_pct": risk.HARD_MAX_SECTOR_PCT,
                      "max_open_positions": risk.HARD_MAX_OPEN_POSITIONS, "min_reward_risk": risk.HARD_MIN_REWARD_RISK},
    }


# ---- routes -------------------------------------------------------------------------------
@app.get("/api/status")
def status():
    e = E()
    with SessionLocal() as db:
        u = e.settings_row(db)
        return {
            "demo": settings.demo, "market_source": e.market.name, "broker": e.broker.name,
            "claude": settings.claude_enabled, "model": settings.claude_model if settings.claude_enabled else None,
            "market_open": e.market.is_open(), "market_time": iso(e.market.now()), "session_rules": e.session_rules,
            "last_cycle": iso(e.last_cycle), "last_scan": e.last_scan_summary, "kill_switch": u.kill_switch, "mode": u.mode,
            "paused_symbols": sorted(s for s, until in e.paused.items() if until > e.market.now()),
        }


@app.get("/api/dashboard")
def dashboard():
    e = E()
    acct = e.broker.account()
    prices = {p.symbol: p.market_price for p in e.broker.positions()}
    with SessionLocal() as db:
        open_trades = [trade_out(t, prices.get(t.symbol)) for t in e.open_trades(db)]
        closed = db.scalars(select(Trade).where(Trade.closed_at.is_not(None))).all()
        snaps = db.scalars(select(EquitySnapshot).order_by(EquitySnapshot.id.desc()).limit(2000)).all()[::-1]
        pending = db.scalar(select(func.count(Proposal.id)).where(Proposal.status.in_(["pending", "idea"]))) or 0
        alerts = db.scalars(select(Alert).order_by(Alert.id.desc()).limit(8)).all()
        unread = db.scalar(select(func.count(Alert.id)).where(Alert.read.is_(False))) or 0

    step = max(1, len(snaps) // 300)
    curve, base_e, base_b = [], None, None
    for sn in snaps[::step]:
        if not sn.benchmark:
            continue
        base_e, base_b = base_e or sn.equity, base_b or sn.benchmark
        curve.append({"t": iso(sn.at), "equity": round(sn.equity, 2), "you": round((sn.equity / base_e - 1) * 100, 3),
                      "sp500": round((sn.benchmark / base_b - 1) * 100, 3)})
    pnls = [t.pnl for t in closed if t.pnl is not None and t.exit_reason != "demo restart"]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    return {
        "account": {"equity": acct.equity, "cash": acct.cash, "buying_power": acct.buying_power,
                    "day_pnl": acct.equity - acct.last_equity,
                    "day_pnl_pct": (acct.equity / acct.last_equity - 1) * 100 if acct.last_equity else 0},
        "positions": open_trades,
        "curve": curve,
        "scoreboard": {
            "trades": len(pnls), "win_rate": len(wins) / len(pnls) if pnls else 0, "total_pnl": round(sum(pnls), 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0, "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else None,
            "you_pct": curve[-1]["you"] if curve else 0, "sp500_pct": curve[-1]["sp500"] if curve else 0,
        },
        "pending_proposals": pending,
        "alerts": [{"id": a.id, "at": iso(a.at), "level": a.level, "title": a.title, "body": a.body, "read": a.read} for a in alerts],
        "unread_alerts": unread,
    }


@app.get("/api/proposals")
def proposals(status: Literal["open", "all"] = "open", limit: int = 50):
    with SessionLocal() as db:
        q = select(Proposal).order_by(Proposal.id.desc()).limit(limit)
        if status == "open":
            q = q.where(Proposal.status.in_(["pending", "idea"]))
        return [proposal_out(p) for p in db.scalars(q).all()]


@app.get("/api/proposals/{pid}")
def proposal(pid: int):
    with SessionLocal() as db:
        p = db.get(Proposal, pid)
        if not p:
            raise HTTPException(404, "not found")
        trade = db.scalar(select(Trade).where(Trade.proposal_id == pid))
        return {**proposal_out(p), "trade": trade_out(trade) if trade else None}


@app.post("/api/proposals/{pid}/approve")
def approve(pid: int):
    ok, msg = E().approve(pid)
    if not ok:
        raise HTTPException(409, msg)
    return {"ok": True, "message": msg}


class RejectIn(BaseModel):
    reason: str = "rejected by you"


@app.post("/api/proposals/{pid}/reject")
def reject(pid: int, body: RejectIn | None = None):
    if not E().reject(pid, (body or RejectIn()).reason):
        raise HTTPException(409, "proposal is no longer open")
    return {"ok": True}


@app.get("/api/trades")
def trades(status: Literal["open", "closed", "all"] = "all", limit: int = 200):
    e = E()
    prices = {p.symbol: p.market_price for p in e.broker.positions()}
    with SessionLocal() as db:
        q = select(Trade).order_by(Trade.id.desc()).limit(limit)
        if status == "open":
            q = q.where(Trade.closed_at.is_(None))
        elif status == "closed":
            q = q.where(Trade.closed_at.is_not(None))
        rows = db.scalars(q).all()
        theses = {p.id: p.thesis for p in db.scalars(select(Proposal).where(Proposal.id.in_([t.proposal_id for t in rows if t.proposal_id]))).all()}
        return [{**trade_out(t, prices.get(t.symbol)), "thesis": theses.get(t.proposal_id)} for t in rows]


@app.post("/api/trades/{tid}/close")
def close_trade(tid: int):
    ok, msg = E().close_trade_now(tid)
    if not ok:
        raise HTTPException(409, msg)
    return {"ok": True}


@app.get("/api/log")
def decision_log(stage: str | None = None, outcome: str | None = None, symbol: str | None = None,
                 exclude: str | None = None, limit: int = 200):
    with SessionLocal() as db:
        q = select(DecisionLog).order_by(DecisionLog.id.desc()).limit(min(limit, 1000))
        if stage:
            q = q.where(DecisionLog.stage == stage)
        if outcome:
            q = q.where(DecisionLog.outcome == outcome)
        if exclude:
            q = q.where(DecisionLog.stage.not_in(exclude.split(",")))
        if symbol:
            q = q.where(DecisionLog.symbol == symbol.upper())
        return [{"id": r.id, "at": iso(r.at), "symbol": r.symbol, "stage": r.stage, "outcome": r.outcome,
                 "reason": r.reason, "detail": r.detail} for r in db.scalars(q).all()]


@app.get("/api/settings")
def get_settings_route():
    with SessionLocal() as db:
        return settings_out(E().settings_row(db), db)


class SettingsIn(BaseModel):
    mode: Literal["research", "copilot", "autopilot"] | None = None
    risk_per_trade_pct: float | None = Field(None, gt=0, le=risk.HARD_MAX_RISK_PER_TRADE_PCT)
    daily_loss_limit_pct: float | None = Field(None, gt=0, le=risk.HARD_MAX_DAILY_LOSS_PCT)
    max_position_pct: float | None = Field(None, gt=0, le=risk.HARD_MAX_POSITION_PCT)
    max_sector_pct: float | None = Field(None, gt=0, le=risk.HARD_MAX_SECTOR_PCT)
    max_open_positions: int | None = Field(None, ge=1, le=risk.HARD_MAX_OPEN_POSITIONS)
    max_trades_per_day: int | None = Field(None, ge=1, le=50)
    min_reward_risk: float | None = Field(None, ge=risk.HARD_MIN_REWARD_RISK, le=5)
    score_threshold: int | None = Field(None, ge=50, le=95)
    halal_only: bool | None = None
    allowed_symbols: list[str] | None = None
    strategy: Literal["day_momentum", "swing", "long_term", "dividend"] | None = None
    language: Literal["en", "ar"] | None = None


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    with SessionLocal() as db:
        u = E().settings_row(db)
        data = body.model_dump(exclude_none=True)
        if data.get("mode") == "autopilot" and not settings_out(u, db)["autopilot"]["unlocked"]:
            raise HTTPException(403, f"Autopilot unlocks after {AUTOPILOT_UNLOCK_TRADES} completed Copilot trades")
        if "allowed_symbols" in data:
            data["allowed_symbols"] = sorted({s.strip().upper() for s in data["allowed_symbols"] if s.strip()})
        for k, v in data.items():
            setattr(u, k, v)
        if data.get("mode") == "autopilot":
            u.autopilot_unlocked = True
        db.commit()
        return settings_out(u, db)


class KillIn(BaseModel):
    on: bool


@app.post("/api/kill")
def kill(body: KillIn):
    E().set_kill_switch(body.on)
    return {"kill_switch": body.on}


@app.post("/api/scan")
def scan_now():
    return E().cycle()


@app.get("/api/briefing")
def briefing(lang: Literal["en", "ar"] = "en", force: bool = False):
    b = E().briefing(lang, force)
    return {"day": b.day, "language": b.language, "body": b.body, "at": iso(b.at), "source": E().agents.source}


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    symbol: str | None = None
    proposal_id: int | None = None
    lang: Literal["en", "ar"] = "en"


@app.post("/api/ask")
def ask(body: AskIn):
    return {"answer": E().ask(body.question, body.symbol, body.proposal_id, body.lang), "source": E().agents.source}


@app.get("/api/market")
def market():
    e = E()
    out = []
    for sym in e.market.universe():
        bars = e.market.minute_bars(sym, 240)
        if len(bars) < 2:
            continue
        f = features.compute(bars, e.market.daily_bars(sym, 30))
        fd = e.market.fundamentals(sym)
        out.append({
            "symbol": sym, "name": fd.name if fd else sym, "sector": fd.sector if fd else "", "price": round(f.price, 2),
            "change_day_pct": round(f.change_day_pct, 2), "change_30m_pct": round(f.change_30m_pct, 2),
            "volume_ratio": round(f.volume_ratio, 2), "rsi": round(f.rsi14, 1), "trend": f.trend,
            "momentum": round(f.momentum_score, 1), "halal": halal.screen(fd).passes,
            "spark": [round(b.c, 2) for b in bars[-60:]],
            "paused": bool((u := e.paused.get(sym)) and u > e.market.now()),
        })
    return out


@app.get("/api/stock/{symbol}")
def stock(symbol: str):
    e = E()
    sym = symbol.upper()
    ctx = e.stock_context(sym)
    if not ctx:
        raise HTTPException(404, "no data for this symbol")
    hr = halal.screen(e.market.fundamentals(sym))
    bars = e.market.minute_bars(sym, 240)
    return {**ctx, "halal": {"passes": hr.passes, "reasons": hr.reasons, "debt_ratio": hr.debt_ratio, "cash_ratio": hr.cash_ratio},
            "bars": [{"t": iso(b.ts), "c": round(b.c, 2), "v": round(b.v)} for b in bars],
            "news": [{"headline": n.headline, "source": n.source, "at": iso(n.published_at), "url": n.url}
                     for n in e.market.news([sym], 10) if sym in n.symbols]}


@app.get("/api/candles/{symbol}")
def candles(symbol: str, tf: Literal["1m", "5m", "15m", "1h", "1D"] = "5m", limit: int = 400):
    """OHLCV candles for the chart, plus our trades in this stock so the chart can mark entries and exits."""
    e = E()
    sym = symbol.upper()
    bars = e.market.history(sym, tf, min(limit, 2000))
    if not bars:
        raise HTTPException(404, "no data for this symbol")
    with SessionLocal() as db:
        trades = db.scalars(select(Trade).where(Trade.symbol == sym).order_by(Trade.id.desc()).limit(50)).all()
    q = e.market.quote(sym)
    return {
        "symbol": sym, "tf": tf,
        "bars": [{"time": int(b.ts.timestamp()), "open": round(b.o, 4), "high": round(b.h, 4), "low": round(b.l, 4),
                  "close": round(b.c, 4), "volume": round(b.v)} for b in bars],
        "trades": [trade_out(t, q.price if q else None) for t in trades],
        "last": q.price if q else bars[-1].c,
    }


@app.post("/api/analyze/{symbol}")
def analyze(symbol: str, propose: bool = False):
    try:
        return E().analyze(symbol, propose)
    except ValueError as err:
        raise HTTPException(404, str(err))


@app.get("/api/mood")
def market_mood():
    e = E()
    if e.mood is None:
        e.update_mood()
    return {**(e.mood.to_dict() if e.mood else {}), "report": e.mood_report}


def _agent_roster() -> list[dict]:
    return [
        {"id": a.id, "name": a.name, "job": a.job, "when": a.when, "plan_no": a.plan_no, "reads": a.data, "writes": a.writes,
         "module": a.module, "kind": a.kind(settings.claude_enabled, settings.agent_team), "agent_key": a.id,
         "apis": a.apis, "skills": [{"name": n, "description": SKILLS[n].description, "sources": SKILLS[n].sources} for n in a.skills]}
        for a in AGENTS
    ]


@app.get("/api/agents")
def agents_overview():
    since = datetime.now(UTC) - timedelta(days=1)
    with SessionLocal() as db:
        calls = db.scalars(select(AgentCall).where(AgentCall.at >= since)).all()
        runs = db.scalars(select(Proposal).order_by(Proposal.id.desc()).limit(12)).all()
        nos = db.scalars(select(DecisionLog).where(DecisionLog.stage == "score").order_by(DecisionLog.id.desc()).limit(1)).all()
    stats: dict[str, dict] = {}
    skill_use: dict[str, int] = {}
    for c in calls:
        key = "coach" if c.agent in ("coach", "briefing") else c.agent
        for sk in c.skills or []:
            skill_use[sk.get("skill", "")] = skill_use.get(sk.get("skill", ""), 0) + 1
        st = stats.setdefault(key, {"calls": 0, "errors": 0, "ms": 0, "tokens": 0})
        st["calls"] += 1
        st["errors"] += 0 if c.ok else 1
        st["ms"] += c.latency_ms
        st["tokens"] += c.input_tokens + c.output_tokens
    roster = _agent_roster()
    for a in roster:
        st = stats.get(a.get("agent_key", ""), {})
        a["calls_24h"] = st.get("calls", 0)
        a["errors_24h"] = st.get("errors", 0)
        a["avg_ms"] = round(st["ms"] / st["calls"]) if st.get("calls") else None
        a["tokens_24h"] = st.get("tokens", 0)
    return {
        "team_mode": settings.agent_team, "claude": settings.claude_enabled, "model": settings.claude_model if settings.claude_enabled else None,
        "agents": roster,
        "skills": [{"name": k, "description": v.description, "sources": v.sources, "calls_24h": skill_use.get(k, 0),
                    "used_by": [a.name for a in AGENTS if k in a.skills]} for k, v in SKILLS.items()],
        "runs": [proposal_out(p) for p in runs],
        "last_rejected": [{"at": iso(n.at), "symbol": n.symbol, "reason": n.reason, "detail": n.detail} for n in nos],
    }


@app.get("/api/sources")
def sources():
    rows = E().extras.sources()
    rows.append({"name": "Anthropic Claude", "provides": "The AI agents", "status": "connected" if settings.claude_enabled else "missing_key",
                 "env": "ANTHROPIC_API_KEY", "note": f"{settings.claude_model} · team: {settings.agent_team}" if settings.claude_enabled else "agents run rule-based"})
    rows.append({"name": "Telegram", "provides": "Phone alerts", "status": "connected" if settings.telegram_bot_token else "missing_key",
                 "env": "TELEGRAM_BOT_TOKEN", "note": ""})
    return rows


# ---- deal finder -----------------------------------------------------------------------------
def _hunt_out(h) -> dict:
    d = h.to_dict()
    if h.trade_id:
        e = E()
        with SessionLocal() as db:
            t = db.get(Trade, h.trade_id)
            if t:
                q = e.market.quote(t.symbol)
                d["trade"] = trade_out(t, q.price if q else None)
    return d


@app.post("/api/hunt")
def hunt_start():
    return _hunt_out(hunter.start(E()))


@app.get("/api/hunt/latest")
def hunt_latest():
    e = E()
    h = e.hunts.get(e.latest_hunt_id) if e.latest_hunt_id else None
    return _hunt_out(h) if h else None


@app.get("/api/hunt/{hunt_id}")
def hunt_get(hunt_id: str):
    h = E().hunts.get(hunt_id)
    if not h:
        raise HTTPException(404, "unknown hunt")
    return _hunt_out(h)


class BuyIn(BaseModel):
    qty: int = Field(ge=1)


@app.post("/api/hunt/{hunt_id}/buy")
def hunt_buy(hunt_id: str, body: BuyIn):
    ok, msg, _ = hunter.buy(E(), hunt_id, body.qty)
    if not ok:
        raise HTTPException(409, msg)
    return _hunt_out(E().hunts[hunt_id])


@app.post("/api/trades/{tid}/keep")
def keep_now(tid: int):
    E().keep_now(tid)
    with SessionLocal() as db:
        t = db.get(Trade, tid)
        if not t:
            raise HTTPException(404, "unknown trade")
        return trade_out(t)


@app.get("/api/reviews")
def reviews(limit: int = 30):
    with SessionLocal() as db:
        return [{"id": r.id, "at": iso(r.at), "day": r.day, "stats": r.stats, "summary": r.summary, "lessons": r.lessons,
                 "proposed_change": r.proposed_change, "change_applied": r.change_applied, "change_verdict": r.change_verdict}
                for r in db.scalars(select(Review).order_by(Review.id.desc()).limit(limit)).all()]


@app.post("/api/reviews/run")
def run_review():
    r = E().review()
    return {"id": r.id, "summary": r.summary}


@app.get("/api/alerts")
def alerts(limit: int = 50):
    with SessionLocal() as db:
        return [{"id": a.id, "at": iso(a.at), "level": a.level, "title": a.title, "body": a.body, "read": a.read}
                for a in db.scalars(select(Alert).order_by(Alert.id.desc()).limit(limit)).all()]


@app.post("/api/alerts/read")
def alerts_read():
    with SessionLocal() as db:
        for a in db.scalars(select(Alert).where(Alert.read.is_(False))).all():
            a.read = True
        db.commit()
    return {"ok": True}


@app.get("/api/usage")
def usage():
    since = datetime.now(UTC) - timedelta(days=1)
    with SessionLocal() as db:
        calls = db.scalars(select(AgentCall).where(AgentCall.at >= since)).all()
        recent = db.scalars(select(AgentCall).order_by(AgentCall.id.desc()).limit(25)).all()
    cost = 0.0
    for c in calls:
        pin, pout = PRICES.get(c.model, PRICES["claude-opus-5-5"])
        cost += (c.input_tokens * pin + c.output_tokens * pout) / 1e6
    return {
        "calls_24h": len(calls), "errors_24h": sum(1 for c in calls if not c.ok),
        "input_tokens_24h": sum(c.input_tokens for c in calls), "output_tokens_24h": sum(c.output_tokens for c in calls),
        "cache_read_tokens_24h": sum(c.cache_read_tokens for c in calls), "est_cost_24h": round(cost, 4),
        "recent": [{"at": iso(c.at), "agent": c.agent, "symbol": c.symbol, "model": c.model, "in": c.input_tokens,
                    "out": c.output_tokens, "ms": c.latency_ms, "ok": c.ok, "error": c.error} for c in recent],
    }
