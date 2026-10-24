"""End-to-end on the demo market: scan → proposals → approve → manage → kill switch → review."""

from sqlalchemy import select

from rahbeh.broker.sim import SimBroker
from rahbeh.config import Settings
from rahbeh.db import DecisionLog, Proposal, SessionLocal, Trade, init_db
from rahbeh.engine import Engine
from rahbeh.market.sim import SimMarket
from rahbeh.pipeline.agents import Agents


def make_engine():
    init_db()
    s = Settings(anthropic_api_key=None, alpaca_api_key=None, alpaca_secret_key=None)
    market = SimMarket(seed=11)
    return Engine(s, market, SimBroker(market), Agents(s))


def test_full_loop():
    e = make_engine()
    executed = False
    for _ in range(60):
        e.cycle()
        with SessionLocal() as db:
            fresh = db.scalars(select(Proposal).where(Proposal.status == "pending").order_by(Proposal.id.desc())).first()
        if fresh and not executed:
            ok, msg = e.approve(fresh.id)  # approve straight away, like a user tapping the alert
            assert ok, msg
            executed = True
    assert executed, "the scanner should produce a trade to approve within 60 simulated minutes"
    with SessionLocal() as db:
        assert db.scalars(select(Trade)).first() is not None
        assert db.scalars(select(DecisionLog).where(DecisionLog.outcome == "no")).first() is not None
    for _ in range(5):
        e.cycle()

    e.set_kill_switch(True)
    assert e.broker.positions() == []
    assert e.cycle()["skipped"] == "kill switch on"
    with SessionLocal() as db:
        assert not db.scalars(select(Trade).where(Trade.closed_at.is_(None))).all()
        assert not db.scalars(select(Proposal).where(Proposal.status == "pending")).all()
    e.set_kill_switch(False)

    review = e.review()
    assert review.summary and review.change_verdict


def test_candles_and_analyze():
    e = make_engine()
    for tf in ("1m", "5m", "1h", "1D"):
        bars = e.market.history("AAPL", tf, 300)
        assert bars and all(a.ts < b.ts for a, b in zip(bars, bars[1:])), tf
    res = e.analyze("AAPL", propose=True)
    assert res["verdict"] in ("trade", "no trade")
    assert {g["name"] for g in res["gates"]} >= {"Data OK", "Score line", "Risk engine"}
    assert (res["proposal_id"] is not None) == (res["verdict"] == "trade")


def test_context_has_extras_and_team():
    e = make_engine()
    e.cycle()
    assert e.mood is not None and e.mood.level in ("calm", "careful", "stormy")
    ctx = e.stock_context("NFLX")
    assert ctx["earnings"]["days_until"] == 1 and ctx["filings"] and ctx["ratings"]["total"] > 0
    team = e.agents.team(ctx)
    assert team["company"]["earnings_risk"] is True and team["news"]["by"] == "rules"
    res = e.analyze("NFLX")
    gate = next(g for g in res["gates"] if g["name"] == "Earnings")
    assert gate["passed"] is False and res["verdict"] == "no trade"


def test_deal_finder_full_loop():
    from rahbeh.team import hunter

    e = make_engine()
    for _ in range(3):
        e.cycle()
    deal_hunt = None
    for _ in range(25):  # the demo market needs a mover; give it a few simulated minutes
        h = hunter.Hunt(id=f"t{_}", started_at="now")
        e.hunts[h.id] = h
        hunter._hunt(e, h)
        assert h.steps and h.steps[0]["agent"] == "mood"
        if h.status == "found":
            deal_hunt = h
            break
        e.cycle()
    assert deal_hunt, "expected the deal finder to find something within 25 simulated minutes"
    d = deal_hunt.deal
    assert d["max_qty"] >= 1 and d["stop"] < d["entry"] < d["target"]
    assert {s["agent"] for s in deal_hunt.steps} >= {"scanner", "news", "chart", "company", "analyst", "devil", "manager", "risk"}

    ok, msg, _ = hunter.buy(e, deal_hunt.id, d["max_qty"] + 1000)
    assert not ok and "at most" in msg  # can't buy more than the risk engine allows
    qty = max(1, d["max_qty"] // 2)
    ok, msg, trade_id = hunter.buy(e, deal_hunt.id, qty)
    assert ok, msg
    with SessionLocal() as db:
        t = db.get(Trade, trade_id)
        assert t.qty == qty and t.origin == "deal_finder"
    e.run_keepers(force_trade_id=trade_id)
    with SessionLocal() as db:
        t = db.get(Trade, trade_id)
        assert t.keeper_log and t.keeper_log[-1]["action"] in ("hold", "tighten", "sell")
        assert t.keeper_log[-1]["skills"]


def test_keeper_rules():
    from rahbeh.pipeline.agents import rules_keeper

    base = {"position": {"symbol": "X", "price": 105, "stop": 98, "r_multiple": 2.5}, "peak_r": 2.6,
            "features": {"ema9": 104, "ema21": 102, "vwap": 101, "rsi14": 60, "atr14": 0.5},
            "headlines_since_entry": [], "mood": "calm", "trail_stop": 103}
    assert rules_keeper(base).action == "tighten"
    assert rules_keeper({**base, "mood": "stormy"}).action == "sell"
    assert rules_keeper({**base, "headlines_since_entry": [{"headline": "probe launched", "sentiment": -0.8}]}).action == "sell"
    faded = {**base, "position": {**base["position"], "price": 101, "r_multiple": 0.5}, "peak_r": 2.0, "trail_stop": 98}
    assert rules_keeper(faded).action == "sell"
    calm = {**base, "position": {**base["position"], "price": 100.5, "r_multiple": 0.25}, "peak_r": 0.3, "trail_stop": 98}
    assert rules_keeper(calm).action == "hold"
