"""Backtester agent (plain code): every trade the AI team finds is tested 1,000+ ways before it can be proposed.

For one live trade: work out which setup is firing now (breakout / VWAP pullback / momentum / opening-range
breakout), then test that setup on the stock and its peers with every filter and exit rule (9 x 128 = 1,152
variants). Pick the best variant on in-sample data among those whose filters the live trade passes, judge it
on out-of-sample data, resample it 1,000 times (Monte Carlo), and hand back a verdict plus the tested
stop / target / holding time.
"""

from __future__ import annotations

import logging

import numpy as np
import threading
import time
import uuid
from datetime import UTC, datetime

from ..market.base import Bar, aggregate
from ..market.universe import FUNDAMENTALS, sector_of
from . import engine as bt
from .data import ET, AlpacaHistory, SimHistory

log = logging.getLogger(__name__)
CACHE_SECONDS = 1800


class Backtester:
    def __init__(self, settings, universe: list[str]):
        self.s = settings
        self.universe = universe
        self.history = SimHistory() if settings.demo else AlpacaHistory(settings)
        self._series: dict[tuple[str, int], tuple[float, bt.Series]] = {}
        self._trade_cache: dict[tuple[str, str], tuple[float, dict]] = {}
        self._lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        self.latest_job: str | None = None

    @property
    def criteria(self) -> bt.Criteria:
        return bt.Criteria(min_oos_trades=self.s.backtest_min_oos_trades, min_oos_exp_r=self.s.backtest_min_oos_exp_r)

    def series(self, symbol: str, days: int | None = None) -> bt.Series:
        days = days or self.s.backtest_days
        key = (symbol, days)
        with self._lock:
            hit = self._series.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        s = self.history.series(symbol, days)
        with self._lock:
            self._series[key] = (time.time(), s)
        return s

    def peers(self, symbol: str) -> list[str]:
        sector = sector_of(symbol)
        same = [x for x in self.universe if x != symbol and sector_of(x) == sector]
        others = sorted((x for x in self.universe if x != symbol and x not in same),
                        key=lambda x: FUNDAMENTALS[x].market_cap if x in FUNDAMENTALS else 0, reverse=True)
        return [symbol, *(same + others)][: self.s.backtest_basket]

    # ---- one trade ---------------------------------------------------------------------------
    def for_trade(self, symbol: str, minute_bars: list[Bar]) -> dict:
        live = live_series(symbol, aggregate(minute_bars, 5))
        if len(live.c) < 25:
            return {"verdict": "not_enough_data", "reasons": ["not enough live bars to classify the setup"], "variants_tested": 0}
        ind = bt.indicators(live)
        setup, vals = bt.live_setup(live, ind)
        note = None
        if setup is None:
            setup, note = "momentum", "no clean setup on the latest bar, so the trade was tested as a momentum entry"
        key = (symbol, setup)
        with self._lock:
            hit = self._trade_cache.get(key)
        if hit and time.time() - hit[0] < 300:
            return {**hit[1], "cached": True}
        started = time.monotonic()
        basket = self.peers(symbol)
        series = [self.series(x) for x in basket]
        res = bt.run(series, setups=[setup], slip_bps=self.s.backtest_slip_bps, criteria=self.criteria,
                     applicable={"setup": setup, "rvol": vals["rvol"], "rsi": vals["rsi"]}, top=10)
        out = compact(res)
        out.update({"setup": setup, "setup_description": bt.SETUPS[setup], "live": vals, "note": note,
                    "basket": basket, "ms": int((time.monotonic() - started) * 1000), "source": self.history.name,
                    "at": datetime.now(UTC).isoformat()})
        if res.best:
            v = res.best["variant"]
            atr5 = max(vals["atr"], vals["price"] * 0.001)
            price = vals["price"]
            out["tuned_plan"] = {
                "entry": round(price, 2), "stop": round(price - v["stop_atr"] * atr5, 2),
                "target": round(price + v["target_r"] * v["stop_atr"] * atr5, 2),
                "max_hold_min": None if v["max_hold"] >= 999 else v["max_hold"] * 5, "trail": v["trail"],
                "expected_r": round(res.best["oos"]["exp_r"], 3), "variant": res.best["key"],
            }
        with self._lock:
            self._trade_cache[key] = (time.time(), out)
        return out

    # ---- strategy lab: the whole market ---------------------------------------------------------
    def start_lab(self, symbols: list[str] | None = None, setups: list[str] | None = None, days: int | None = None) -> dict:
        jid = uuid.uuid4().hex[:10]
        job = {"id": jid, "status": "running", "started_at": datetime.now(UTC).isoformat(), "progress": "loading history",
               "symbols": symbols or self.universe, "setups": setups or list(bt.SETUPS), "days": days or self.s.backtest_days}
        self.jobs[jid] = job
        self.latest_job = jid

        def work():
            try:
                series = []
                for i, sym in enumerate(job["symbols"]):
                    job["progress"] = f"loading history {i + 1}/{len(job['symbols'])}: {sym}"
                    series.append(self.series(sym, job["days"]))
                job["progress"] = f"testing {len(job['setups']) * len(bt.FILTERS) * len(bt.EXITS):,} variants"
                t0 = time.monotonic()
                res = bt.run(series, setups=job["setups"], slip_bps=self.s.backtest_slip_bps, criteria=self.criteria, top=40)
                job["result"] = {**compact(res, top=40), "ms": int((time.monotonic() - t0) * 1000), "source": self.history.name}
                job["status"] = "done"
            except Exception as e:
                log.exception("lab failed")
                job["status"], job["error"] = "failed", f"{type(e).__name__}: {e}"
            job["finished_at"] = datetime.now(UTC).isoformat()

        threading.Thread(target=work, daemon=True, name=f"lab-{jid}").start()
        return job


def compact(res: bt.Result, top: int = 10) -> dict:
    d = res.to_dict()
    d["leaderboard"] = d["leaderboard"][:top]
    eq = d["equity"]
    if len(eq) > 300:
        step = len(eq) / 300
        d["equity"] = [eq[int(i * step)] for i in range(300)] + [eq[-1]]
    return d


def live_series(symbol: str, bars: list[Bar]) -> bt.Series:
    """Live 5-minute bars as a Series, without dropping off-hours bars (the demo market trades around the clock)."""
    days: dict = {}
    day_idx, bod = [], []
    for b in bars:
        et = b.ts.astimezone(ET)
        d = days.setdefault(et.date(), len(days))
        day_idx.append(d)
        bod.append(max(0, (et.hour * 60 + et.minute - 570) // 5))
    f = lambda attr: np.array([getattr(b, attr) for b in bars], dtype=float)  # noqa: E731
    return bt.Series(symbol, np.array([int(b.ts.timestamp()) for b in bars], dtype=np.int64), f("o"), f("h"), f("l"), f("c"), f("v"),
                     np.array(day_idx, dtype=np.int64), np.array(bod, dtype=np.int64))
