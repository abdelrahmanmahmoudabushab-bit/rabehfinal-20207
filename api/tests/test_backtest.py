"""The backtester must be honest: no lookahead, conservative fills, and it must not find an edge in noise."""

from datetime import UTC, date, datetime, time, timedelta

import numpy as np

from rahbeh.backtest import engine as bt
from rahbeh.backtest.data import ET, SimHistory, to_series, trading_days


def random_walk(sym: str, seed: int, days: int = 60):
    rng = np.random.default_rng(seed)
    price, rows = 100.0, []
    for d in trading_days(date(2026, 10, 23), days):
        for b in range(78):
            o = price
            c = o * (1 + rng.normal(0, 0.0022))
            h, lo = max(o, c) * (1 + abs(rng.normal(0, 0.0009))), min(o, c) * (1 - abs(rng.normal(0, 0.0009)))
            ts = (datetime.combine(d, time(9, 30), ET) + timedelta(minutes=5 * b)).astimezone(UTC)
            rows.append((ts, o, h, lo, c, rng.uniform(5e3, 1.5e4)))
            price = c
    return to_series(sym, rows)


def test_no_edge_in_pure_noise():
    res = bt.run([random_walk(f"S{i}", i) for i in range(12)], slip_bps=3.0)
    assert res.variants_tested == len(bt.FILTERS) * len(bt.EXITS) * len(bt.SETUPS) >= 1000
    assert res.median_oos_exp_r < 0  # costs make the typical variant lose
    assert res.verdict != "edge"
    assert res.best["oos"]["exp_r"] < res.best["is"]["exp_r"]  # the in-sample winner was luck


def _series_from_closes(closes, highs=None, lows=None):
    d0 = trading_days(date(2026, 10, 23), 1)[0]
    rows = []
    for b, c in enumerate(closes):
        o = closes[b - 1] if b else c
        h = highs[b] if highs else max(o, c)
        lo = lows[b] if lows else min(o, c)
        ts = (datetime.combine(d0, time(9, 30), ET) + timedelta(minutes=5 * b)).astimezone(UTC)
        rows.append((ts, o, h, lo, c, 1000.0))
    return to_series("T", rows)


def test_fills_enter_next_open_and_stop_first():
    closes = [100.0] * 30 + [101.0] + [101.0] * 47
    highs = [c + 0.05 for c in closes]
    lows = [c - 0.05 for c in closes]
    # the bar after the signal spans both a big target and the stop: the stop must win
    highs[31], lows[31] = 110.0, 90.0
    s = _series_from_closes(closes, highs, lows)
    ind = bt.indicators(s)
    sim = bt.simulate(s, ind, np.array([30]), slip_bps=0.0)
    entry = s.o[31]
    assert entry == 101.0  # next bar's open, never the signal bar's close-time price
    r = sim["r"][0]
    k_idx = bt.EXITS.index((1.0, 1.0, "none", 999))
    assert r[k_idx] < 0  # stop first


def test_target_hit_pays_target_r():
    closes = [100.0] * 30 + [101.0] + [101.0] * 47
    highs = [c + 0.01 for c in closes]
    lows = [c - 0.01 for c in closes]
    highs[33] = 150.0  # target hit cleanly two bars after entry
    s = _series_from_closes(closes, highs, lows)
    ind = bt.indicators(s)
    sim = bt.simulate(s, ind, np.array([30]), slip_bps=0.0)
    for tgt in bt.TARGET_R:
        e = bt.EXITS.index((2.0, tgt, "none", 999))
        assert abs(sim["r"][0][e] - tgt) < 1e-6


def test_finds_a_planted_edge():
    """A market where breakouts genuinely keep going must show up as an edge, out of sample too."""
    rng = np.random.default_rng(1)
    series = []
    for k in range(10):
        price, rows, run = 50.0, [], 0
        for d in trading_days(date(2026, 10, 23), 60):
            for b in range(78):
                o = price
                drift = 0.004 if run > 0 else 0.0
                run = max(0, run - 1)
                c = o * (1 + drift + rng.normal(0, 0.0015))
                if run == 0 and rng.random() < 0.03:
                    run = 8
                h, lo = max(o, c) * 1.0005, min(o, c) * 0.9995
                ts = (datetime.combine(d, time(9, 30), ET) + timedelta(minutes=5 * b)).astimezone(UTC)
                rows.append((ts, o, h, lo, c, 1e4 * (3 if run else 1)))
                price = c
        series.append(to_series(f"E{k}", rows))
    res = bt.run(series, setups=["momentum"])
    assert res.verdict == "edge", res.reasons
    assert res.best["oos"]["exp_r"] > 0.05


def test_monte_carlo():
    mc = bt.monte_carlo(np.array([1.0, -1.0, 2.0, -1.0, 1.5] * 10))
    assert mc["runs"] == 1000 and 0 <= mc["p_loss"] < 0.2 and mc["p95_mdd_r"] >= mc["median_mdd_r"]


def test_sim_history_shape():
    s = SimHistory(date(2026, 10, 23)).series("AAPL", 10)
    assert len(s.t) == 780 and s.bod.max() == 77 and len(np.unique(s.day)) == 10
