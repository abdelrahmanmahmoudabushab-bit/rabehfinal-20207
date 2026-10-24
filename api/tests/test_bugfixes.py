"""Regression tests for bugs found in the bug hunt."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from rahbeh.broker.sim import SimBroker
from rahbeh.config import Settings
from rahbeh.db import AgentCall, Proposal, SessionLocal, Trade, init_db
from rahbeh.engine import Engine
from rahbeh.market.sim import SimMarket
from rahbeh.pipeline import risk
from rahbeh.pipeline.agents import Agents, rules_keeper

ET = ZoneInfo("America/New_York")


def make_engine(seed=9):
    init_db()
    s = Settings(anthropic_api_key=None, alpaca_api_key=None, alpaca_secret_key=None)
    m = SimMarket(seed=seed)
    return Engine(s, m, SimBroker(m), Agents(s))


def test_new_york_midnight_queries_are_not_off_by_hours():
    """SQLite drops time zones; a call at 22:00 New York time yesterday must not count as 'today'."""
    e = make_engine()
    midnight = datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as db:
        for r in db.scalars(select(AgentCall)).all():
            db.delete(r)
        db.add(AgentCall(agent="x", model="claude-opus-5-5", at=midnight.astimezone(UTC) - timedelta(hours=2),
                         input_tokens=1_000_000, output_tokens=0))
        db.commit()
        assert not db.scalars(select(AgentCall).where(AgentCall.at >= midnight)).all()
        row = db.scalars(select(AgentCall)).first()
        assert row.at.tzinfo is not None  # timestamps come back timezone-aware
    e.agents._spend_cache = None
    assert e.agents.spend_today() == 0


def test_demo_todays_pnl_resets_each_day():
    m = SimMarket(seed=2, history_minutes=30)
    b = SimBroker(m)
    a0 = b.account()
    px = m.quote("AAPL").price
    b.submit_bracket("AAPL", 10, px * 0.5, px * 2, px)
    m._clock += timedelta(days=1)  # next day
    a1 = b.account()
    assert a0.last_equity == 100_000  # day one: P&L measured from the starting cash
    assert a1.last_equity == a1.equity  # day two: today's P&L starts at zero
    m._clock += timedelta(hours=1)
    assert b.account().last_equity == a1.last_equity  # and stays anchored for the rest of that day


def test_keeper_follows_tested_exits():
    base = {"position": {"symbol": "X", "price": 105, "stop": 98, "r_multiple": 2.5}, "peak_r": 2.6,
            "features": {"ema9": 100, "ema21": 102, "vwap": 106, "rsi14": 90, "atr14": 0.5},
            "headlines_since_entry": [], "mood": "calm", "trail_stop": 103}
    assert rules_keeper(base).action in ("sell", "tighten")  # untested trade: the keeper manages it
    tested = {**base, "tested_plan": {"variant": "breakout|...", "max_hold_min": 30, "trail": "none"}}
    assert rules_keeper(tested).action == "hold"  # tested trade: code runs the tested exits
    assert rules_keeper({**tested, "mood": "stormy"}).action == "sell"  # but events still trigger a sale


def test_tested_breakeven_trail_moves_only_to_breakeven():
    e = make_engine()
    px = e.market.quote("AAPL").price
    assert e.broker.submit_bracket("AAPL", 1, px - 2, px + 50, px).ok
    with SessionLocal() as db:
        t = Trade(symbol="AAPL", qty=1, entry_price=px - 10, initial_stop=px - 12, stop=px - 12, target=px + 50,
                  opened_at=e.market.now(), notes=[], keeper_log=[], plan={"variant": "v", "trail": "breakeven"})
        db.add(t)
        db.commit()
        tid = t.id
    e.manage_positions()  # price is +5R above entry
    with SessionLocal() as db:
        t = db.get(Trade, tid)
        assert abs(t.stop - (px - 10)) < 1e-9  # breakeven, not trailed 1R behind price like untested trades
        db.delete(t)
        db.commit()
    e.broker.close("AAPL")


def test_half_day_close():
    close = datetime(2026, 11, 27, 13, 0, tzinfo=ET)  # day after Thanksgiving
    assert not risk.should_flatten(datetime(2026, 11, 27, 12, 45, tzinfo=ET), True, close)
    assert risk.should_flatten(datetime(2026, 11, 27, 12, 50, tzinfo=ET), True, close)
    assert risk.last_entry_time(close).hour == 12 and risk.last_entry_time(close).minute == 30
    assert risk.last_entry_time(None) == risk.LAST_ENTRY_ET


def test_stale_idea_cannot_be_approved():
    e = make_engine()
    with SessionLocal() as db:
        p = Proposal(symbol="AAPL", score=80, entry=100, stop=99, target=102, qty=1, risk_amount=1, thesis="t",
                     analyst={}, devil={}, manager={}, features={}, risk_checks=[], status="pending",
                     created_at=e.market.now() - timedelta(minutes=20))
        db.add(p)
        db.commit()
        pid = p.id
    ok, msg = e.approve(pid)
    assert not ok and "older than 15 minutes" in msg
    with SessionLocal() as db:
        assert db.get(Proposal, pid).status == "expired"


def test_reconcile_with_broker():
    e = make_engine()
    with SessionLocal() as db:
        for t in db.scalars(select(Trade).where(Trade.closed_at.is_(None))).all():
            db.delete(t)
        db.add(Trade(symbol="MSFT", qty=5, entry_price=400, initial_stop=395, stop=395, target=410,
                     opened_at=e.market.now(), notes=[], keeper_log=[], plan={}))
        db.commit()
    px = e.market.quote("NVDA").price
    e.broker.submit_bracket("NVDA", 1, px * 0.9, px * 1.1, px)  # bought outside Rahbeh's records
    notes = e.reconcile()
    assert any("MSFT" in n and "closed" in n for n in notes) and any("NVDA" in n and "not managed" in n for n in notes)
    with SessionLocal() as db:
        assert db.scalar(select(Trade).where(Trade.symbol == "MSFT")).exit_reason == "closed outside app"


def test_backtest_stops_are_tradable_live():
    import numpy as np

    from rahbeh.backtest import engine as bt

    r = bt.risk_size(np.array([0.01, 5.0, 50.0]), np.array([100.0, 100.0, 100.0]))
    assert r[0] / 100 * 100 >= risk.MIN_STOP_DISTANCE_PCT and r[2] / 100 * 100 <= risk.MAX_STOP_DISTANCE_PCT


def test_api_token_required_when_set(monkeypatch):
    from fastapi.testclient import TestClient

    import rahbeh.main as main

    monkeypatch.setattr(main.settings, "api_token", "s3cret")
    with TestClient(main.app) as c:
        assert c.get("/api/status").status_code == 401
        assert c.post("/api/kill", json={"on": True}).status_code == 401
        assert c.get("/api/status", headers={"x-rahbeh-token": "wrong"}).status_code == 401
        assert c.get("/api/status", headers={"x-rahbeh-token": "s3cret"}).status_code == 200
