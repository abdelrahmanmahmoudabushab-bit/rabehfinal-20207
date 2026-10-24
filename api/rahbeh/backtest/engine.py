"""Vectorized intraday backtester.

What it tests: 4 entry setups x 9 filters (relative volume x RSI cap) x 128 exit rules
(stop size x target x breakeven trail x max hold) = 4,608 variants, each across every stock in the basket.

Rules that keep it honest:
- No lookahead: a signal uses only bars up to and including the signal bar's close; the trade enters at the
  NEXT bar's open, plus slippage.
- Conservative fills: if the stop and the target are both inside one bar, the stop is assumed to hit first.
  Gaps through a stop fill at the (worse) open. Slippage is charged on entry and exit.
- Intraday only: every trade is closed by 15:50 ET at the latest.
- Walk-forward: variants are ranked on the first 70% of the history (in-sample) and judged on the last 30%
  (out-of-sample), which they never saw.
- One signal per stock per setup per cooldown window, so a single move is not counted ten times.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import product

import numpy as np

SETUPS = {
    "breakout": "Close above the 20-bar high in an uptrend (EMA 9 > EMA 21)",
    "vwap_pullback": "Uptrend pulls back to VWAP, holds it and closes green",
    "momentum": "Up more than 0.6% in 30 minutes, above VWAP, in an uptrend",
    "orb": "First break above the opening 30-minute range",
}
RVOL_FILTERS = (1.0, 1.5, 2.0)
RSI_CAPS = (70.0, 80.0, 101.0)  # 101 = no cap
STOP_ATR = (1.0, 1.5, 2.0, 3.0)
TARGET_R = (1.0, 1.5, 2.0, 3.0)
TRAILS = ("none", "breakeven")
MAX_HOLD = (6, 12, 24, 999)  # 5-minute bars: 30 min, 1 h, 2 h, until the close
EXITS = list(product(STOP_ATR, TARGET_R, TRAILS, MAX_HOLD))  # 128
FILTERS = list(product(RVOL_FILTERS, RSI_CAPS))  # 9
BARS_PER_DAY = 78
LAST_BAR = 75  # the 15:45–15:50 bar: everything is flat by 15:50
LAST_ENTRY_BAR = 71  # no new entries after 15:30
WINDOW = BARS_PER_DAY
COOLDOWN_BARS = 6


@dataclass
class Series:
    """5-minute regular-session bars for one stock."""

    symbol: str
    t: np.ndarray  # epoch seconds
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray  # noqa: E741
    c: np.ndarray
    v: np.ndarray
    day: np.ndarray  # session index (0, 1, 2 ...)
    bod: np.ndarray  # bar of day (0 = 09:30)


@dataclass
class Indicators:
    ema9: np.ndarray
    ema21: np.ndarray
    vwap: np.ndarray
    atr: np.ndarray
    rsi: np.ndarray
    rvol: np.ndarray
    high20: np.ndarray
    ret6: np.ndarray
    orh: np.ndarray  # opening-range high (NaN until the range is complete)


MIN_STOP_PCT = 0.0016  # just inside the live risk engine's limits (0.15%–8%), so every tested trade is tradable live
MAX_STOP_PCT = 0.079


def risk_size(raw, entry):
    """Stop distance, clipped to what the live risk engine accepts."""
    return np.clip(raw, entry * MIN_STOP_PCT, entry * MAX_STOP_PCT)


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    k = 2 / (n + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


def indicators(s: Series) -> Indicators:
    c, h, lo, v = s.c, s.h, s.l, s.v
    n = len(c)
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - lo, np.maximum(np.abs(h - prev_c), np.abs(lo - prev_c)))
    atr = np.convolve(tr, np.ones(14) / 14, mode="full")[:n]
    atr[:14] = np.cumsum(tr[:14]) / np.arange(1, 15)[: min(14, n)]
    # session VWAP
    tp_v = (h + lo + c) / 3 * v
    vwap = np.empty(n)
    start = 0
    for i in range(1, n + 1):
        if i == n or s.day[i] != s.day[i - 1]:
            cv = np.cumsum(v[start:i])
            vwap[start:i] = np.cumsum(tp_v[start:i]) / np.where(cv > 0, cv, 1)
            start = i
    # RSI (Wilder)
    d = np.diff(c, prepend=c[0])
    gain, loss = np.maximum(d, 0), np.maximum(-d, 0)
    ag, al = _ema(gain, 27), _ema(loss, 27)  # EMA with alpha 1/14 ~ span 27
    rsi = 100 - 100 / (1 + ag / np.where(al > 0, al, 1e-12))
    # relative volume: this bar vs the average of the previous 78 bars
    cs = np.concatenate([[0.0], np.cumsum(v)])
    idx = np.arange(n)
    lo_i = np.maximum(idx - 78, 0)
    prev_avg = (cs[idx] - cs[lo_i]) / np.maximum(idx - lo_i, 1)
    rvol = np.divide(v, prev_avg, out=np.ones(n), where=prev_avg > 0)
    # highest high of the previous 20 bars (excluding this one)
    high20 = np.full(n, np.inf)
    for i in range(20, n):
        high20[i] = h[i - 20:i].max()
    ret6 = np.zeros(n)
    ret6[6:] = c[6:] / c[:-6] - 1
    orh = np.full(n, np.nan)
    for dd in np.unique(s.day):
        m = np.where(s.day == dd)[0]
        first = m[s.bod[m] < 6]
        if len(first) == 6:
            orh[m[s.bod[m] >= 6]] = h[first].max()
    return Indicators(_ema(c, 9), _ema(c, 21), vwap, atr, rsi, rvol, high20, ret6, orh)


def setup_signals(s: Series, ind: Indicators, setup: str) -> np.ndarray:
    c, o, lo = s.c, s.o, s.l
    up = ind.ema9 > ind.ema21
    window = (s.bod >= 1) & (s.bod <= LAST_ENTRY_BAR)
    if setup == "breakout":
        sig = up & (c > ind.high20)
    elif setup == "vwap_pullback":
        sig = up & (lo <= ind.vwap + 0.25 * ind.atr) & (c > ind.vwap) & (c > o)
    elif setup == "momentum":
        sig = up & (ind.ret6 > 0.006) & (c > ind.vwap)
    elif setup == "orb":
        prev_c = np.concatenate([[np.inf], c[:-1]])
        sig = ~np.isnan(ind.orh) & (c > np.nan_to_num(ind.orh, nan=np.inf)) & (prev_c <= np.nan_to_num(ind.orh, nan=np.inf))
        sig &= np.concatenate([[False], s.day[1:] == s.day[:-1]])
    else:
        raise ValueError(setup)
    sig = sig & window
    # cooldown: at most one signal per COOLDOWN_BARS
    out = np.zeros_like(sig)
    last = -10**9
    for i in np.flatnonzero(sig):
        if i - last >= COOLDOWN_BARS and i + 1 < len(c) and s.day[i + 1] == s.day[i]:
            out[i] = True
            last = i
    return out


def simulate(s: Series, ind: Indicators, sig_idx: np.ndarray, slip_bps: float) -> dict[str, np.ndarray]:
    """Outcome of every signal under every exit rule: returns r (S x 128) and pct (S x 128)."""
    S = len(sig_idx)
    if S == 0:
        return {"r": np.zeros((0, len(EXITS))), "pct": np.zeros((0, len(EXITS)))}
    n = len(s.c)
    slip = slip_bps / 10_000
    cols = sig_idx[:, None] + 1 + np.arange(WINDOW)[None, :]
    inb = cols < n
    colc = np.minimum(cols, n - 1)
    O, H, L, C = s.o[colc], s.h[colc], s.l[colc], s.c[colc]
    same_day = (s.day[colc] == s.day[sig_idx][:, None]) & inb
    # last tradable position in the window: the 15:45-15:50 bar of the signal's day
    flat_ok = same_day & (s.bod[colc] <= LAST_BAR)
    day_end = flat_ok.sum(axis=1) - 1  # index into the window
    entry = s.o[np.minimum(sig_idx + 1, n - 1)] * (1 + slip)
    atr = ind.atr[sig_idx]
    pos = np.arange(WINDOW)[None, :]
    r_out = np.empty((S, len(EXITS)))
    pct_out = np.empty((S, len(EXITS)))
    rows = np.arange(S)
    for e_i, (k, tgt, trail, hold) in enumerate(EXITS):
        R = risk_size(k * atr, entry)
        stop0 = entry - R
        target = entry + tgt * R
        end = np.minimum(day_end, hold - 1)
        valid = pos <= end[:, None]
        if trail == "breakeven":
            reached = (H >= (entry + R)[:, None]) & valid
            fr = np.where(reached.any(axis=1), reached.argmax(axis=1), WINDOW)
            stop_lvl = np.where(pos > fr[:, None], np.maximum(stop0, entry)[:, None], stop0[:, None])
        else:
            stop_lvl = np.broadcast_to(stop0[:, None], (S, WINDOW))
        hit_s = (L <= stop_lvl) & valid
        hit_t = (H >= target[:, None]) & valid
        fs = np.where(hit_s.any(axis=1), hit_s.argmax(axis=1), WINDOW)
        ft = np.where(hit_t.any(axis=1), hit_t.argmax(axis=1), WINDOW)
        stop_first = (fs <= ft) & (fs < WINDOW)  # same bar -> stop first (conservative)
        tgt_first = (ft < fs) & (ft < WINDOW)
        fs_c, ft_c = np.minimum(fs, WINDOW - 1), np.minimum(ft, WINDOW - 1)
        stop_px = np.minimum(stop_lvl[rows, fs_c], O[rows, fs_c])  # gap through the stop fills at the open
        tgt_px = np.maximum(target, O[rows, ft_c])
        time_px = C[rows, np.maximum(end, 0)]
        exit_px = np.where(stop_first, stop_px, np.where(tgt_first, tgt_px, time_px)) * (1 - slip)
        r_out[:, e_i] = (exit_px - entry) / R
        pct_out[:, e_i] = exit_px / entry - 1
    return {"r": r_out, "pct": pct_out}


@dataclass
class Variant:
    setup: str
    min_rvol: float
    rsi_cap: float
    stop_atr: float
    target_r: float
    trail: str
    max_hold: int

    @property
    def key(self) -> str:
        hold = "close" if self.max_hold >= 999 else f"{self.max_hold * 5}m"
        cap = "none" if self.rsi_cap > 100 else f"{self.rsi_cap:.0f}"
        return f"{self.setup}|rvol≥{self.min_rvol}|rsi<{cap}|stop {self.stop_atr}ATR|target {self.target_r}R|{self.trail}|hold {hold}"


def stats(r: np.ndarray, pct: np.ndarray) -> dict:
    """Column-wise metrics for a (trades x variants) block of R multiples, in time order."""
    n = r.shape[0]
    if n == 0:
        z = np.zeros(r.shape[1])
        return {"n": z, "win": z, "exp_r": z, "pf": z, "mdd_r": z, "t": z, "avg_pct": z}
    wins = (r > 0).sum(axis=0)
    gp = np.where(r > 0, r, 0).sum(axis=0)
    gl = -np.where(r < 0, r, 0).sum(axis=0)
    cum = np.cumsum(r, axis=0)
    mdd = (np.maximum.accumulate(cum, axis=0) - cum).max(axis=0)
    mean = r.mean(axis=0)
    sd = r.std(axis=0, ddof=1) if n > 1 else np.ones(r.shape[1])
    return {"n": np.full(r.shape[1], n), "win": wins / n, "exp_r": mean, "pf": np.where(gl > 0, gp / np.maximum(gl, 1e-9), np.inf),
            "mdd_r": mdd, "t": np.where(sd > 0, mean / sd * np.sqrt(n), 0), "avg_pct": pct.mean(axis=0) * 100}


def monte_carlo(r: np.ndarray, runs: int = 1000, seed: int = 0) -> dict:
    """Resample the trade list 1,000 times: how likely is a loss, and how deep can the drawdown get?"""
    if len(r) < 2:
        return {"runs": 0}
    rng = np.random.default_rng(seed)
    sims = r[rng.integers(0, len(r), size=(runs, len(r)))]
    totals = sims.sum(axis=1)
    cum = np.cumsum(sims, axis=1)
    dd = (np.maximum.accumulate(cum, axis=1) - cum).max(axis=1)
    return {"runs": runs, "p_loss": float((totals < 0).mean()), "median_total_r": float(np.median(totals)),
            "p5_total_r": float(np.percentile(totals, 5)), "p95_total_r": float(np.percentile(totals, 95)),
            "median_mdd_r": float(np.median(dd)), "p95_mdd_r": float(np.percentile(dd, 95)),
            "hist": np.histogram(totals, bins=24)[0].tolist(), "hist_edges": [float(x) for x in np.histogram_bin_edges(totals, bins=24)]}


@dataclass
class Criteria:
    min_oos_trades: int = 15
    min_is_trades: int = 20
    min_oos_exp_r: float = 0.05
    max_p_loss: float = 0.3


@dataclass
class Result:
    symbols: list[str]
    setups: list[str]
    bars: int
    days: int
    variants_tested: int
    signals: int
    split_at: int  # epoch seconds where out-of-sample starts
    slip_bps: float
    best: dict | None
    leaderboard: list[dict]
    share_oos_positive: float
    median_oos_exp_r: float
    is_oos_rank_corr: float
    heatmap: dict
    setup_summary: list[dict]
    equity: list[dict]
    monte_carlo: dict
    verdict: str  # edge | no_edge | not_enough_data
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def run(series: list[Series], setups: list[str] | None = None, slip_bps: float = 3.0, oos_frac: float = 0.3,
        applicable: dict | None = None, criteria: Criteria | None = None, top: int = 25) -> Result:
    """Backtest every variant across every stock. `applicable` limits which filter variants count as
    candidates for selection (e.g. only filters the live trade actually passes)."""
    setups = setups or list(SETUPS)
    crit = criteria or Criteria()
    all_t = np.concatenate([s.t for s in series]) if series else np.zeros(0)
    split = int(np.quantile(all_t, 1 - oos_frac)) if len(all_t) else 0
    rows: list[dict] = []
    trade_blocks: dict[tuple, dict] = {}
    total_signals = 0
    per_setup: dict[str, dict] = {}
    inds = [(s, indicators(s)) for s in series]
    for setup in setups:
        R, P, T, RV, RS = [], [], [], [], []
        for s, ind in inds:
            idx = np.flatnonzero(setup_signals(s, ind, setup))
            sim = simulate(s, ind, idx, slip_bps)
            R.append(sim["r"])
            P.append(sim["pct"])
            T.append(s.t[idx])
            RV.append(ind.rvol[idx])
            RS.append(ind.rsi[idx])
        r = np.concatenate(R) if R else np.zeros((0, len(EXITS)))
        pct = np.concatenate(P) if P else np.zeros((0, len(EXITS)))
        t = np.concatenate(T) if T else np.zeros(0)
        rv = np.concatenate(RV) if RV else np.zeros(0)
        rs = np.concatenate(RS) if RS else np.zeros(0)
        order = np.argsort(t, kind="stable")
        r, pct, t, rv, rs = r[order], pct[order], t[order], rv[order], rs[order]
        total_signals += len(t)
        per_setup[setup] = {"setup": setup, "signals": int(len(t)), "description": SETUPS[setup]}
        for f_i, (min_rvol, rsi_cap) in enumerate(FILTERS):
            m = (rv >= min_rvol) & (rs < rsi_cap)
            is_m, oos_m = m & (t < split), m & (t >= split)
            st_is, st_oos = stats(r[is_m], pct[is_m]), stats(r[oos_m], pct[oos_m])
            ok_filter = applicable is None or (applicable.get("setup") == setup and applicable["rvol"] >= min_rvol and applicable["rsi"] < rsi_cap)
            for e_i, (k, tgt, trail, hold) in enumerate(EXITS):
                v = Variant(setup, min_rvol, rsi_cap, k, tgt, trail, hold)
                rows.append({
                    "key": v.key, "variant": asdict(v), "applicable": bool(ok_filter),
                    "is": {kk: float(vv[e_i]) for kk, vv in st_is.items()},
                    "oos": {kk: float(vv[e_i]) for kk, vv in st_oos.items()},
                })
                trade_blocks[(setup, f_i, e_i)] = {"m": m, "e": e_i}
            per_setup[setup].setdefault("_data", (r, pct, t))

    variants = len(rows)
    oos_exp = np.array([x["oos"]["exp_r"] for x in rows]) if rows else np.zeros(0)
    is_exp = np.array([x["is"]["exp_r"] for x in rows]) if rows else np.zeros(0)
    has_oos = np.array([x["oos"]["n"] >= 1 for x in rows]) if rows else np.zeros(0, bool)
    share_pos = float((oos_exp[has_oos] > 0).mean()) if has_oos.any() else 0.0
    med_oos = float(np.median(oos_exp[has_oos])) if has_oos.any() else 0.0
    corr = _rank_corr(is_exp[has_oos], oos_exp[has_oos]) if has_oos.sum() > 5 else 0.0

    # Selection uses ONLY in-sample numbers; out-of-sample is the honest score of that choice
    candidates = [x for x in rows if x["applicable"] and x["is"]["n"] >= crit.min_is_trades]
    candidates.sort(key=lambda x: (x["is"]["exp_r"], x["is"]["t"]), reverse=True)
    best = candidates[0] if candidates else None

    mc: dict = {"runs": 0}
    equity: list[dict] = []
    reasons: list[str] = []
    verdict = "not_enough_data"
    if best:
        v = best["variant"]
        r_all, pct_all, t_all = per_setup[v["setup"]]["_data"]
        f_i = FILTERS.index((v["min_rvol"], v["rsi_cap"]))
        e_i = EXITS.index((v["stop_atr"], v["target_r"], v["trail"], v["max_hold"]))
        m = trade_blocks[(v["setup"], f_i, e_i)]["m"]
        rr, tt = r_all[m, e_i], t_all[m]
        cum = np.cumsum(rr)
        equity = [{"t": int(a), "cum_r": round(float(b), 3), "oos": bool(a >= split)} for a, b in zip(tt, cum)]
        oos_r = rr[tt >= split]
        mc = monte_carlo(oos_r if len(oos_r) >= 10 else rr)
        o = best["oos"]
        if o["n"] < crit.min_oos_trades:
            reasons.append(f"only {int(o['n'])} out-of-sample trades (need {crit.min_oos_trades})")
        if o["exp_r"] < crit.min_oos_exp_r:
            reasons.append(f"out-of-sample expectancy {o['exp_r']:+.2f}R (need ≥ {crit.min_oos_exp_r:+.2f}R)")
        if best["is"]["exp_r"] <= 0:
            reasons.append("even the best in-sample variant loses money")
        if mc.get("runs") and mc["p_loss"] > crit.max_p_loss:
            reasons.append(f"{mc['p_loss']:.0%} chance of a losing run in Monte Carlo (max {crit.max_p_loss:.0%})")
        if o["n"] < crit.min_oos_trades:
            verdict = "not_enough_data"
        else:
            verdict = "edge" if not reasons else "no_edge"
        if verdict == "edge":
            reasons.append(f"best in-sample variant held up out of sample: {o['exp_r']:+.2f}R per trade over {int(o['n'])} trades")
    elif applicable is not None and not any(x["applicable"] for x in rows):
        reasons.append(f"the live trade passes none of the tested filters (relative volume {applicable['rvol']:.2f}x, "
                       f"RSI {applicable['rsi']:.0f}; the loosest filter needs ≥{min(RVOL_FILTERS)}x)")
    else:
        reasons.append(f"no variant had {crit.min_is_trades}+ in-sample trades")

    # stop x target heatmap of out-of-sample expectancy (for the chosen setup/filter, trail+hold of best)
    heat = {"stops": list(STOP_ATR), "targets": list(TARGET_R), "cells": []}
    if best:
        v = best["variant"]
        lookup = {(x["variant"]["setup"], x["variant"]["min_rvol"], x["variant"]["rsi_cap"], x["variant"]["stop_atr"],
                   x["variant"]["target_r"], x["variant"]["trail"], x["variant"]["max_hold"]): x for x in rows}
        for k in STOP_ATR:
            heat["cells"].append([round(lookup[(v["setup"], v["min_rvol"], v["rsi_cap"], k, tg, v["trail"], v["max_hold"])]["oos"]["exp_r"], 3)
                                  for tg in TARGET_R])

    for st in per_setup.values():
        st.pop("_data", None)
        sub = [x for x in rows if x["variant"]["setup"] == st["setup"] and x["oos"]["n"] > 0]
        st["share_oos_positive"] = round(float(np.mean([x["oos"]["exp_r"] > 0 for x in sub])), 3) if sub else 0.0
        st["best_oos_exp_r"] = round(max((x["oos"]["exp_r"] for x in sub), default=0.0), 3)

    leaderboard = sorted((x for x in rows if x["is"]["n"] >= crit.min_is_trades), key=lambda x: x["is"]["exp_r"], reverse=True)[:top]
    days = int(sum(len(np.unique(s.day)) for s in series) / max(len(series), 1))
    return Result(
        symbols=[s.symbol for s in series], setups=setups, bars=int(sum(len(s.t) for s in series)), days=days,
        variants_tested=variants, signals=total_signals, split_at=split, slip_bps=slip_bps, best=best,
        leaderboard=leaderboard, share_oos_positive=round(share_pos, 3), median_oos_exp_r=round(med_oos, 4),
        is_oos_rank_corr=round(corr, 3), heatmap=heat, setup_summary=list(per_setup.values()), equity=equity,
        monte_carlo=mc, verdict=verdict, reasons=reasons,
    )


def _rank_corr(a: np.ndarray, b: np.ndarray) -> float:
    """Spearman rank correlation: do variants that looked good in-sample stay good out of sample?"""
    if len(a) < 3:
        return 0.0
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    if ra.std() == 0 or rb.std() == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def live_setup(s: Series, ind: Indicators) -> tuple[str | None, dict]:
    """Which setup (if any) is firing on the latest bar, and the live filter values."""
    i = len(s.c) - 1
    vals = {"rvol": float(ind.rvol[i]), "rsi": float(ind.rsi[i]), "atr": float(ind.atr[i]), "price": float(s.c[i])}
    for setup in SETUPS:
        sig = setup_signals_raw(s, ind, setup)
        if sig[i]:
            return setup, vals
    return None, vals


def setup_signals_raw(s: Series, ind: Indicators, setup: str) -> np.ndarray:
    """Like setup_signals, without the session window and cooldown (for classifying the live bar)."""
    c, o, lo = s.c, s.o, s.l
    up = ind.ema9 > ind.ema21
    if setup == "breakout":
        return up & (c > ind.high20)
    if setup == "vwap_pullback":
        return up & (lo <= ind.vwap + 0.25 * ind.atr) & (c > ind.vwap) & (c > o)
    if setup == "momentum":
        return up & (ind.ret6 > 0.006) & (c > ind.vwap)
    orh = np.nan_to_num(ind.orh, nan=np.inf)
    return c > orh
