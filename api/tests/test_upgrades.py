"""Speed and smarts upgrades: regime filter, stricter bar, edge-based sizing, live setup health, worker process,
nightly precompute, per-agent models, price tape and the new report endpoints."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
from sqlalchemy import select

from rahbeh.backtest import engine as bt
from rahbeh.backtest.data import SimHistory
from rahbeh.backtest.service import Backtester
from rahbeh.broker.base import Account
from rahbeh.broker.sim import SimBroker
from rahbeh.config import Settings
from rahbeh.db import Alert, SessionLocal, Trade, init_db
from rahbeh.engine import Engine
from rahbeh.market.sim import SimMarket
from rahbeh.market.stream import PriceTape
from rahbeh.pipeline import risk
from rahbeh.pipeline.agents import Agents

ET = bt.ET


def make_engine(seed=21, **kw):
    init_db()
    s = Settings(anthropic_api_key=None, alpaca_api_key=None, alpaca_secret_key=None, **kw)
    m = SimMarket(seed=seed)
    return Engine(s, m, SimBroker(m), Agents(s))


def fake_series(symbol, day_paths):
    """5-minute series with one price path (list of closes) per session, starting 2026-09-01."""
    t, o, h, lo, c, v, day, bod = [], [], [], [], [], [], [], []
    d0 = datetime(2026, 9, 1, 13, 30, tzinfo=UTC)
    for di, path in enumerate(day_paths):
        prev = path[0]
        for b, px in enumerate(path):
            t.append(int((d0 + timedelta(days=di, minutes=5 * b)).timestamp()))
            o.append(prev); c.append(px); h.append(max(prev, px) * 1.0005); lo.append(min(prev, px) * 0.9995); v.append(1000.0)
            day.append(di); bod.append(b)
            prev = px
    a = lambda x, dt=float: np.array(x, dtype=dt)  # noqa: E731
    return bt.Series(symbol, a(t, np.int64), a(o), a(h), a(lo), a(c), a(v), a(day, np.int64), a(bod, np.int64))


# ---- market regime -------------------------------------------------------------------------
def _paths(kind, n_days, seed):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n_days):
        steps = rng.normal(0.0006 if kind == "trend" else 0, 0.0008 if kind == "trend" else 0.002, 78)
        out.append(list(100 * np.cumprod(1 + steps)))
    return out


def test_regime_labels_trending_vs_choppy_and_never_peek():
    spy = fake_series("SPY", _paths("trend", 12, 1) + _paths("chop", 12, 2))
    labels, current = bt.session_regimes(spy)
    days = sorted(labels)
    assert current == 0  # the last sessions went nowhere
    assert all(labels[d] == 0 for d in days[-4:])  # the choppy stretch at the end is labeled choppy
    flipped, cur2 = bt.session_regimes(fake_series("SPY", _paths("chop", 12, 2) + _paths("trend", 12, 1)))
    days2 = sorted(flipped)
    assert cur2 == 1 and all(flipped[d] == 1 for d in days2[-4:])  # and the reverse order is labeled trending

    # nothing that happens LATER may change an earlier label (the threshold is an expanding median)
    base_days = _paths("trend", 12, 1) + _paths("chop", 12, 2)
    cut = 16
    altered = [list(p) for p in base_days[:cut]] + [[100 + 40 * i / 77 for i in range(78)] for _ in range(len(base_days) - cut)]
    labels2, _ = bt.session_regimes(fake_series("SPY", altered))
    last_same = date(2026, 9, 1) + timedelta(days=cut)  # session `cut` is the first altered one; its label only uses earlier ones
    assert [d for d in days if d <= last_same]
    for d in days:
        if d <= last_same:
            assert labels2.get(d) == labels.get(d), d
    # and a session's own prices never change its own label
    own = [list(p) for p in base_days]
    own[15] = [100 + 30 * i / 77 for i in range(78)]
    assert bt.session_regimes(fake_series("SPY", own))[0][days[15]] == labels[days[15]]


def test_regime_blocks_setup_that_loses_in_current_market():
    series = [SimHistory().series(s, 40) for s in ("AAPL", "MSFT", "NVDA", "AMD")]
    labels, _ = bt.session_regimes(SimHistory().series("SPY", 40))
    for s in series:
        bt.tag_regime(s, labels)
    res = bt.run(series, setups=["momentum"], applicable=None, current_regime=0)
    assert set(res.regime["by_regime"]) <= {"trending", "choppy"} and res.regime["current"] == "choppy"
    # force the rule: a current regime whose expectancy is negative must produce a reason
    crit = bt.Criteria(min_regime_trades=1, min_oos_t=-99, deflate=0, min_oos_exp_r=-99, max_p_loss=1.1)
    for cur in (0, 1):
        r = bt.run(series, setups=["momentum"], criteria=crit, current_regime=cur)
        by = r.regime["by_regime"].get(bt.REGIME_NAMES[cur])
        lost = bool(by and by["exp_r"] <= 0)
        assert any("lost money in" in x for x in r.reasons) == lost


# ---- stricter bar --------------------------------------------------------------------------
def test_bar_rises_with_variants_tested():
    series = [SimHistory().series(s, 40) for s in ("AAPL", "MSFT", "NVDA", "AMD")]
    easy = bt.run(series, setups=["momentum"], criteria=bt.Criteria(min_oos_trades=1, min_oos_t=0, deflate=0))
    hard = bt.run(series, setups=["momentum"], criteria=bt.Criteria(min_oos_trades=1, min_oos_t=0, deflate=3.0))
    assert easy.selection["t_bar"] == 0 and hard.selection["t_bar"] > 15
    assert hard.verdict != "edge" and any("t-stat" in x for x in hard.reasons)
    assert hard.selection["candidates"] > 100 and hard.selection["luck_bar"] > 2.5


def test_random_walk_still_finds_nothing_under_production_bar():
    rng = np.random.default_rng(5)
    paths = [list(100 * np.cumprod(1 + rng.normal(0, 0.002, 78))) for _ in range(40)]
    res = bt.run([fake_series("RW", paths)], setups=["momentum"])
    assert res.verdict != "edge"


# ---- sizing --------------------------------------------------------------------------------
def _ctx(equity=100_000):
    acct = Account(equity=equity, cash=equity, buying_power=equity * 4, last_equity=equity)
    return risk.RiskContext(account=acct, positions=[], sector_of={}, realized_pnl_today=0, trades_today=0, kill_switch=False,
                            now=datetime(2026, 10, 21, 15, 0, tzinfo=UTC), session_rules=False)


def test_size_multiplier_only_shrinks_and_zero_blocks():
    lim = risk.Limits(1.0, 2.0, 100, 100, 4, 6, 1.5)  # wide position cap, so the 1% risk rule is what sizes the trade
    base = risk.TradeRequest("AAPL", "Technology", 100.0, 93.0, 114.0, 30)
    full = risk.evaluate(base, _ctx(), lim)
    assert full.approved and full.risk_amount <= 1_000.0001 and full.qty == 142  # the 1% cap sizes it
    greedy = risk.evaluate(risk.TradeRequest("AAPL", "Technology", 100.0, 93.0, 114.0, 30, size_multiplier=5.0), _ctx(), lim)
    assert greedy.qty == full.qty  # a multiplier above 1 is ignored: the cap is hard
    half = risk.evaluate(risk.TradeRequest("AAPL", "Technology", 100.0, 93.0, 114.0, 30, size_multiplier=0.5, size_note="weak edge"), _ctx(), lim)
    assert half.approved and half.qty == full.qty // 2
    paused = risk.evaluate(risk.TradeRequest("AAPL", "Technology", 100.0, 93.0, 114.0, 30, size_multiplier=0.0, size_note="setup paused"), _ctx(), lim)
    assert not paused.approved and any(c.name == "setup_health" and not c.passed for c in paused.checks)


def test_edge_and_volatility_scale_size():
    e = make_engine()
    with SessionLocal() as db:
        strong = {"verdict": "edge", "best": {"oos": {"exp_r": 0.5}}, "setup": "zzz_none", "live": {"atr": 0.5, "price": 100}}
        weak = {"verdict": "edge", "best": {"oos": {"exp_r": 0.1}}, "setup": "zzz_none", "live": {"atr": 0.5, "price": 100}}
        wild = {"verdict": "edge", "best": {"oos": {"exp_r": 0.5}}, "setup": "zzz_none", "live": {"atr": 4, "price": 100}}
        untested = {"verdict": "no_edge", "setup": "zzz_none"}
        ms = {k: e.size_multiplier(db, v)[0] for k, v in dict(strong=strong, weak=weak, wild=wild, untested=untested).items()}
    assert ms["strong"] == 1.0 and 0.4 <= ms["weak"] < 0.5 and ms["wild"] == 0.7 and ms["untested"] == 0.6


def test_losing_setup_is_cut_then_paused_with_alert():
    e = make_engine()
    now = e.market.now()

    def add(n, r):
        with SessionLocal() as db:
            for _ in range(n):
                db.add(Trade(symbol="AAPL", qty=1, entry_price=100, initial_stop=99, stop=99, target=102, pnl=r, r_multiple=r,
                             exit_reason="stop", opened_at=now - timedelta(hours=2), closed_at=now - timedelta(hours=1),
                             notes=[], plan={"setup": "healthtest", "expected_r": 0.3}))
            db.commit()

    btr = {"verdict": "edge", "best": {"oos": {"exp_r": 0.5}}, "setup": "healthtest", "live": {}}
    with SessionLocal() as db:
        assert e.size_multiplier(db, btr)[0] == 1.0  # no live history yet
    add(9, -0.4)
    with SessionLocal() as db:
        assert e.setup_health(db)["healthtest"]["status"] == "cut"
        assert e.size_multiplier(db, btr)[0] == 0.5
    add(7, -0.4)
    with SessionLocal() as db:
        assert e.setup_health(db)["healthtest"]["status"] == "paused"
        m, note = e.size_multiplier(db, btr)
        assert m == 0.0 and "paused" in note
        assert db.scalars(select(Alert).where(Alert.title.contains("healthtest"))).first() is not None
        for t in db.scalars(select(Trade).where(Trade.exit_reason == "stop")).all():
            db.delete(t)
        db.commit()


# ---- worker process, cache and precompute -------------------------------------------------------
def test_worker_process_gives_the_same_answer():
    series = [SimHistory().series(s, 30) for s in ("AAPL", "MSFT", "NVDA")]
    inline = Backtester(Settings(backtest_workers=0), ["AAPL"])._run(series, setups=["breakout"])
    b = Backtester(Settings(backtest_workers=1), ["AAPL"])
    try:
        remote = b._run(series, setups=["breakout"])
    finally:
        b.shutdown()
    assert (remote.verdict, remote.variants_tested, remote.signals) == (inline.verdict, inline.variants_tested, inline.signals)
    assert remote.best["key"] == inline.best["key"]


def test_precompute_makes_the_intraday_verdict_instant_and_plan_stays_fresh():
    e = make_engine()
    bt_ = e.backtester
    st = bt_.precompute(["AAPL"], budget_seconds=120)
    assert st["status"] == "done" and st["done"] == st["total"] == 36
    assert any(k[0] == "AAPL" for k in bt_._core_cache)
    bars = e.market.minute_bars("AAPL", 400)
    first = bt_.for_trade("AAPL", bars)
    second = bt_.for_trade("AAPL", bars)
    assert second.get("cached") is True
    if first.get("tuned_plan"):  # rebuilt from the live price each time, never copied from the cache
        assert second["tuned_plan"]["entry"] == round(second["live"]["price"], 2)
    # a different live price must give a different plan from the same cached test
    moved = [type(b)(b.ts, b.o * 1.02, b.h * 1.02, b.l * 1.02, b.c * 1.02, b.v) for b in bars]
    third = bt_.for_trade("AAPL", moved)
    if third.get("tuned_plan") and second.get("tuned_plan"):
        assert third["tuned_plan"]["entry"] != second["tuned_plan"]["entry"]


# ---- agents ----------------------------------------------------------------------------------
def test_specialists_use_the_small_model_and_skip_effort():
    s = Settings(anthropic_api_key="test", claude_model="claude-opus-5-5", specialist_model="claude-haiku-5-5")
    a = Agents(s)
    assert a.model_for("news") == "claude-haiku-5-5" and a.model_for("mood") == "claude-haiku-5-5"
    assert a.model_for("analyst") == a.model_for("manager") == a.model_for("keeper") == "claude-opus-5-5"
    assert Agents(Settings(anthropic_api_key="test", specialist_model="")).model_for("news") == "claude-opus-5-5"

    seen = []

    def parse(**kw):
        seen.append(kw)
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0),
                               stop_reason="end_turn", parsed_output=object(), content=[])

    a.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    init_db()
    a._run("news", "AAPL", "{}", dict)
    a._run("analyst", "AAPL", "{}", dict)
    assert seen[0]["model"] == "claude-haiku-5-5" and "output_config" not in seen[0]
    assert seen[1]["model"] == "claude-opus-5-5" and seen[1]["output_config"]["effort"] == "medium"
    assert seen[1]["system"][-1]["cache_control"] == {"type": "ephemeral"}  # the static prompt is cache-marked


# ---- price stream ----------------------------------------------------------------------------
def test_price_tape_flags_sharp_moves_and_staleness():
    now = [0.0]
    tape = PriceTape(move_pct=1.0, window_s=60, clock=lambda: now[0])
    assert tape.update("X", 100.0) is False
    now[0] = 20
    assert tape.update("X", 100.4) is False
    now[0] = 40
    assert tape.update("X", 101.2) is True  # +1.2% inside a minute
    assert tape.fresh_price("X") == 101.2
    now[0] = 100
    assert tape.fresh_price("X") is None  # stale: callers fall back to polling
    assert tape.update("X", 101.0) is False  # the old prints aged out of the window


# ---- endpoints -------------------------------------------------------------------------------
def test_new_endpoints():
    from fastapi.testclient import TestClient

    import rahbeh.main as main

    with TestClient(main.app) as c:
        r = c.get("/api/review/agents").json()
        assert {"agents", "blocked_by", "by_analyst_score", "by_devil_severity"} <= set(r)
        assert "setups" in c.get("/api/review/setups").json()
        p = c.get("/api/backtest/precompute").json()
        assert p["workers"] == 0 and "cached_verdicts" in p
        u = c.get("/api/usage").json()
        assert "cache_saved_24h" in u
