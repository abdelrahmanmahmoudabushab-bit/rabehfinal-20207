"""Regression tests for gaps found between what the project claimed and what it did."""


import numpy as np
from sqlalchemy import select

from rahbeh.backtest import engine as bt
from rahbeh.broker.base import Account
from rahbeh.broker.sim import SimBroker
from rahbeh.config import Settings
from rahbeh.db import Alert, Proposal, SessionLocal, Trade, init_db
from rahbeh.engine import Engine
from rahbeh.market.base import Fundamentals
from rahbeh.market.extras import EarningsInfo, parse_finnhub_earnings
from rahbeh.market.sim import SimMarket
from rahbeh.pipeline import halal, risk
from rahbeh.pipeline.agents import Agents


def make_engine(seed=5, **kw):
    init_db()
    s = Settings(anthropic_api_key=None, alpaca_api_key=None, alpaca_secret_key=None, **kw)
    m = SimMarket(seed=seed)
    return Engine(s, m, SimBroker(m), Agents(s))


# ---- backtester honesty rules ----------------------------------------------------------------
def day_series(opens, highs, lows, closes):
    n = len(closes)
    f = lambda x: np.array(x, dtype=float)  # noqa: E731
    return bt.Series("T", np.arange(n, dtype=np.int64) * 300, f(opens), f(highs), f(lows), f(closes), np.full(n, 1000.0),
                     np.zeros(n, dtype=np.int64), np.arange(n, dtype=np.int64))


def flat_day(price=100.0, n=78):
    return [price] * n, [price] * n, [price] * n, [price] * n


def exit_index(stop_atr, target_r, trail, hold):
    return bt.EXITS.index((stop_atr, target_r, trail, hold))


def run_signal(s, at=10, slip=3.0):
    ind = bt.indicators(s)
    ind.atr[:] = 1.0  # a 1.0 ATR so risk is $1.0 x the stop multiple
    return bt.simulate(s, ind, np.array([at]), slip)


def test_slippage_is_charged_on_entry_and_exit():
    o, h, lo, c = flat_day()
    r = run_signal(day_series(o, h, lo, c))["r"]
    assert (r < 0).all()  # a trade that goes nowhere loses the spread: 3 bp in and 3 bp out
    e = exit_index(1.0, 3.0, "none", 6)
    assert abs(r[0, e] - (100 * (1 - 0.0003) - 100 * (1 + 0.0003)) / 1.0) < 1e-6


def test_stop_wins_when_stop_and_target_are_in_the_same_bar():
    o, h, lo, c = flat_day()
    h[11], lo[11] = 110.0, 90.0  # the next bar spans both the target and the stop
    r = run_signal(day_series(o, h, lo, c))["r"]
    assert r[0, exit_index(1.0, 1.0, "none", 999)] <= -1.0  # stop assumed first


def test_gap_through_the_stop_fills_at_the_worse_open():
    o, h, lo, c = flat_day()
    o[12], h[12], lo[12], c[12] = 95.0, 95.5, 94.5, 95.0  # the bar after entry opens 5 below a 1.0 stop
    r = run_signal(day_series(o, h, lo, c))["r"]
    assert r[0, exit_index(1.0, 3.0, "none", 999)] < -4.0  # filled near 95, not at the 99 stop


def test_everything_is_flat_by_the_1550_bar():
    o, h, lo, c = flat_day()
    for b in range(76, 78):  # prices after 15:50 must never matter
        o[b], h[b], lo[b], c[b] = 150.0, 150.0, 150.0, 150.0
    c[75] = 101.0
    r = run_signal(day_series(o, h, lo, c), at=70)["r"]
    assert r[0, exit_index(3.0, 3.0, "none", 999)] < 1.0  # held to the 15:45-15:50 bar's close (~101), not 150


def test_entry_is_the_next_bars_open_not_the_signal_close():
    o, h, lo, c = flat_day()
    o[11] = 102.0  # the signal bar closed at 100; the next bar opens at 102
    h[11], lo[11], c[11] = 102.0, 102.0, 102.0
    for b in range(12, 78):
        o[b] = h[b] = lo[b] = c[b] = 102.0
    r = run_signal(day_series(o, h, lo, c), slip=0.0)["r"]
    assert abs(r[0, exit_index(1.0, 3.0, "none", 999)]) < 1e-9  # bought at 102 and sold at 102: no free 2 points


# ---- safety checks that used to fail open ---------------------------------------------------------
def _ctx(require):
    acct = Account(equity=100_000, cash=100_000, buying_power=400_000, last_equity=100_000)
    from datetime import UTC, datetime

    return risk.RiskContext(account=acct, positions=[], sector_of={}, realized_pnl_today=0, trades_today=0, kill_switch=False,
                            now=datetime(2026, 10, 21, 15, 0, tzinfo=UTC), session_rules=False, require_earnings=require)


def test_unknown_earnings_block_live_trades_but_not_demo():
    lim = risk.Limits(1.0, 2.0, 100, 100, 4, 6, 1.5)
    req = risk.TradeRequest("AAPL", "Technology", 100.0, 93.0, 114.0, None, earnings_known=False)
    live = risk.evaluate(req, _ctx(True), lim)
    assert not live.approved and any(c.name == "earnings" and "unknown" in c.detail for c in live.checks)
    assert risk.evaluate(req, _ctx(False), lim).approved
    known_none = risk.TradeRequest("AAPL", "Technology", 100.0, 93.0, 114.0, None, earnings_known=True)
    assert risk.evaluate(known_none, _ctx(True), lim).approved  # calendar read, nothing in the next 100 days


def test_earnings_known_flag_follows_the_data():
    assert EarningsInfo().known is False
    got = parse_finnhub_earnings({"earningsCalendar": []}, [], __import__("datetime").date(2026, 10, 21))
    assert got.known is True and got.next_date is None


def test_kill_switch_reports_positions_it_could_not_close():
    e = make_engine()
    px = e.market.quote("AAPL").price
    assert e.broker.submit_bracket("AAPL", 1, px * 0.9, px * 1.1, px).ok  # held at the broker, not tracked by the app
    real_close = e.broker.close

    class Res:
        ok, message, fill_price = False, "broker down", None

    e.broker.close = lambda sym: Res()
    e.set_kill_switch(True)
    assert any("AAPL" in f and "broker down" in f for f in e.kill_failed)
    with SessionLocal() as db:
        assert db.scalars(select(Alert).where(Alert.title.contains("still open"))).first() is not None
    e.broker.close = real_close
    e.set_kill_switch(False)
    e.set_kill_switch(True)
    assert e.kill_failed == [] and e.broker.positions() == []  # it also closes positions the app did not open
    e.set_kill_switch(False)


def test_autopilot_count_ignores_restart_closes_and_simulated_trades():
    import rahbeh.main as main

    e = make_engine()
    now = e.market.now()
    with SessionLocal() as db:
        for t in db.scalars(select(Trade)).all():
            db.delete(t)
        for reason, sim in (("stop", True), ("target", True), ("demo restart", True), ("closed outside app", True), ("stop", False)):
            db.add(Trade(symbol="AAPL", qty=1, entry_price=100, initial_stop=99, stop=99, target=102, mode="copilot", sim=sim,
                         exit_reason=reason, opened_at=now, closed_at=now, notes=[]))
        db.commit()
        u = e.settings_row(db)
        out = main.settings_out(u, db)
        assert out["autopilot"]["copilot_trades"] == 2  # only the two real simulated completions, in a simulated account
        for t in db.scalars(select(Trade)).all():
            db.delete(t)
        db.commit()


# ---- entry limit and alert levels ---------------------------------------------------------------
def test_entry_limit_sits_slip_above_the_live_price_and_stale_ideas_expire():
    e = make_engine(max_entry_slip_bps=10.0, max_plan_drift_pct=0.4)
    q = e.market.quote("MSFT").price
    seen = {}
    real = e.broker.submit_bracket

    def spy(sym, qty, stop, target, entry, limit_price=None):
        seen["limit"] = limit_price
        return real(sym, qty, stop, target, entry, limit_price=limit_price)

    e.broker.submit_bracket = spy
    with SessionLocal() as db:
        u = e.settings_row(db)
        p = Proposal(symbol="MSFT", score=80, entry=q, stop=q * 0.93, target=q * 1.14, qty=1, risk_amount=1, thesis="t", analyst={},
                     devil={}, manager={}, features={}, risk_checks=[], status="pending", created_at=e.market.now(),
                     backtest={"verdict": "edge", "best": {"oos": {"exp_r": 0.5}}, "setup": "x", "live": {}})
        db.add(p)
        db.flush()
        ok, msg = e.execute(db, p, u, qty=1)
        assert ok, msg
        assert abs(seen["limit"] - round(q * 1.001, 2)) < 0.011
        stale = Proposal(symbol="MSFT", score=80, entry=q / 1.01, stop=q * 0.9, target=q * 1.2, qty=1, risk_amount=1, thesis="t",
                         analyst={}, devil={}, manager={}, features={}, risk_checks=[], status="pending", created_at=e.market.now())
        db.add(stale)
        db.flush()
        ok, msg = e.execute(db, stale, u, qty=1)
        assert not ok and "past the planned entry" in msg and stale.status == "expired"
        db.rollback()
    e.broker.close("MSFT")


# ---- deal finder runs the data and cooldown checks ---------------------------------------------------
def test_deal_finder_skips_cooling_stocks():
    from rahbeh.team import hunter

    e = make_engine()
    for _ in range(3):
        e.cycle()
    h = hunter.Hunt(id="cool", started_at="now")
    e.hunts[h.id] = h
    hunter._hunt(e, h)
    first = [r["symbol"] for r in h.ranking[:3]]
    for sym in first:
        e._cooldown(sym)
    h2 = hunter.Hunt(id="cool2", started_at="now")
    e.hunts[h2.id] = h2
    hunter._hunt(e, h2)
    skipped = {s["symbol"] for s in h2.steps if "cooling down" in s["text"]}
    assert skipped & set(first)  # the stocks we just cooled were skipped
    assert all(e._cooling(sym) for sym in skipped)  # and nothing was skipped that was not cooling
    assert not any(e._cooling(c["symbol"]) for c in h2.candidates)  # no cooling stock reached the agents


# ---- halal keywords ----------------------------------------------------------------------------------
def test_halal_industry_keywords():
    def f(industry):
        return Fundamentals("X", "X", "Industrials", industry, 100e9, 10e9, 2e9, 5e9, 5e9)

    for bad in ("Aerospace & Defense", "Firearms and Ammunition", "Casinos & Gaming", "Pork Processing", "Online Betting"):
        assert not halal.screen(f(bad)).passes, bad
    assert halal.screen(f("Video Game Software")).passes  # no longer blocked just for the word 'gaming'
