"""The profitability fixes: PDT rule, limit entries, AI budget, rules-vs-Claude A/B, reviewer window, swing mode."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from rahbeh.broker.base import Account
from rahbeh.broker.sim import SimBroker
from rahbeh.config import Settings
from rahbeh.db import AgentCall, SessionLocal, Shadow, Trade, init_db
from rahbeh.engine import Engine
from rahbeh.market.sim import SimMarket
from rahbeh.pipeline import risk
from rahbeh.pipeline.agents import Agents, AnalystReport, call_cost

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)
LIM = risk.Limits(1.0, 2.0, 20, 40, 4, 6, 1.5)


def ctx(**kw):
    base = dict(account=Account(20_000, 20_000, 20_000, 20_000), positions=[], sector_of={}, realized_pnl_today=0,
                trades_today=0, kill_switch=False, now=NOW, session_rules=True)
    base.update(kw)
    return risk.RiskContext(**base)


REQ = risk.TradeRequest("AAPL", "Technology", 100, 98, 104)


def test_pattern_day_trader_rule():
    assert risk.evaluate(REQ, ctx(daytrades_5d=2), LIM).approved
    d = risk.evaluate(REQ, ctx(daytrades_5d=3), LIM)
    assert not d.approved and any(c.name == "pdt" for c in d.failed)
    assert risk.evaluate(REQ, ctx(daytrades_5d=3, swing=True), LIM).approved  # overnight holds aren't day trades
    big = ctx(daytrades_5d=10, account=Account(50_000, 50_000, 50_000, 50_000))
    assert risk.evaluate(REQ, big, LIM).approved  # the rule only applies under $25k


def test_limit_entry_never_chases():
    m = SimMarket(seed=3, history_minutes=60)
    b = SimBroker(m)
    px = m.quote("AAPL").price
    res = b.submit_bracket("AAPL", 1, px * 0.98, px * 1.04, px, limit_price=px * 0.99)
    assert not res.ok and "limit" in res.message
    assert b.submit_bracket("AAPL", 1, px * 0.98, px * 1.04, px, limit_price=px * 1.01).ok


def make_engine(**kw):
    init_db()
    s = Settings(anthropic_api_key=None, alpaca_api_key=None, alpaca_secret_key=None, **kw)
    m = SimMarket(seed=5)
    return Engine(s, m, SimBroker(m), Agents(s))


def test_ai_budget_cap_falls_back_to_rules():
    e = make_engine(daily_ai_budget_usd=0.5)
    with SessionLocal() as db:
        db.add(AgentCall(agent="analyst", model="claude-opus-5-5", input_tokens=200_000, output_tokens=10_000, at=datetime.now(UTC)))
        db.commit()
    assert call_cost("claude-opus-5-5", 200_000, 10_000) > 0.5
    e.agents._spend_cache = None
    assert e.agents.over_budget()


def test_shadow_ab_records_and_fills():
    e = make_engine()
    e.cycle()
    ctx_ = e.stock_context("AAPL")
    rep = AnalystReport(score=80, direction="long", thesis="t", news_view="", chart_view="", company_view="", bullish_points=[], risks=[])
    e.record_shadow("AAPL", ctx_, rep, "claude", 65)
    e.record_shadow("MSFT", ctx_, rep, "heuristic", 65)  # rules-only runs are not A/B samples
    for _ in range(61):
        e.market.tick()
    e.fill_shadows()
    with SessionLocal() as db:
        rows = db.scalars(select(Shadow).where(Shadow.symbol == "AAPL")).all()
        assert rows and rows[-1].claude_go and rows[-1].fwd_60 is not None and rows[-1].fwd_30 is not None
        assert not db.scalars(select(Shadow).where(Shadow.symbol == "MSFT")).all()


def test_reviewer_needs_twenty_trades():
    e = make_engine()
    e.cycle()
    with SessionLocal() as db:
        for t in db.scalars(select(Trade)).all():
            db.delete(t)
        for i in range(5):
            db.add(Trade(symbol="AAPL", qty=1, entry_price=100, initial_stop=99, stop=99, target=102, pnl=-1, r_multiple=-1,
                         exit_reason="stop", opened_at=e.market.now() - timedelta(hours=1), closed_at=e.market.now(), notes=[]))
        db.commit()
    e.agents.reviewer = lambda payload: (
        __import__("rahbeh.pipeline.agents", fromlist=["ReviewerReport"]).ReviewerReport(
            summary="s", lessons=["l"], suggested_score_threshold=80, suggested_min_reward_risk=1.5, reasoning="r"), "rules")
    r = e.review()
    assert not r.change_applied and "need 20" in r.change_verdict


def test_swing_mode_skips_forced_close():
    e = make_engine()
    with SessionLocal() as db:
        u = e.settings_row(db)
        u.strategy = "swing"
        db.commit()
    e.session_rules = True  # pretend it is 15:55 on a real session
    import rahbeh.engine as eng

    orig = eng.risk.should_flatten
    eng.risk.should_flatten = lambda now, rules: True
    try:
        px = e.market.quote("AAPL").price
        assert e.broker.submit_bracket("AAPL", 1, px * 0.9, px * 1.2, px).ok
        with SessionLocal() as db:
            db.add(Trade(symbol="AAPL", qty=1, entry_price=px, initial_stop=px * 0.9, stop=px * 0.9, target=px * 1.2,
                         opened_at=e.market.now(), notes=[], keeper_log=[], plan={}))
            db.commit()
        e.manage_positions()
        with SessionLocal() as db:
            t = db.scalar(select(Trade).where(Trade.symbol == "AAPL", Trade.closed_at.is_(None)))
            assert t is not None  # swing positions are not flattened at 15:50
    finally:
        eng.risk.should_flatten = orig
        with SessionLocal() as db:
            u = e.settings_row(db)
            u.strategy = "day_momentum"
            db.commit()
