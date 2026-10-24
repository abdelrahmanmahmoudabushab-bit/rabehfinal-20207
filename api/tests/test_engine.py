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
