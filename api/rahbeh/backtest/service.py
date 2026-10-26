"""Backtester agent (plain code): every trade the AI team finds is tested 1,000+ ways before it can be proposed.

For one live trade: work out which setup is firing now (breakout / VWAP pullback / momentum / opening-range
breakout), then test that setup on the stock and its peers with every filter and exit rule (9 x 128 = 1,152
variants). Pick the best variant on in-sample data among those whose filters the live trade passes, judge it
on out-of-sample data, resample it 1,000 times (Monte Carlo), and hand back a verdict plus the tested
stop / target / holding time.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import UTC, datetime, timedelta
from multiprocessing import get_context

import numpy as np

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
        self._core_cache: dict[tuple, tuple[float, dict]] = {}
        self._lock = threading.Lock()
        self._pool: ProcessPoolExecutor | None = None
        self._regime: tuple[float, dict, int | None] | None = None
        self.precompute_status: dict = {"status": "idle"}
        self.jobs: dict[str, dict] = {}
        self.latest_job: str | None = None

    @property
    def criteria(self) -> bt.Criteria:
        return bt.Criteria(min_oos_trades=self.s.backtest_min_oos_trades, min_oos_exp_r=self.s.backtest_min_oos_exp_r,
                           min_oos_t=self.s.backtest_min_oos_t, deflate=self.s.backtest_deflate)

    def series(self, symbol: str, days: int | None = None) -> bt.Series:
        days = days or self.s.backtest_days
        key = (symbol, days)
        with self._lock:
            hit = self._series.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        s = self.history.series(symbol, days)
        try:
            labels, _ = self.regime_info(days)
            if labels:
                bt.tag_regime(s, labels)
        except Exception as e:
            log.warning("regime tagging failed for %s: %s", symbol, e)
        with self._lock:
            self._series[key] = (time.time(), s)
        return s

    # ---- market regime (trending vs choppy), from the S&P 500's previous sessions ----------------
    def regime_info(self, days: int | None = None) -> tuple[dict, int | None]:
        days = days or self.s.backtest_days
        with self._lock:
            hit = self._regime
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1], hit[2]
        spy = self.history.series("SPY", days)
        labels, current = bt.session_regimes(spy, today=datetime.now(ET).date())
        with self._lock:
            self._regime = (time.time(), labels, current)
        return labels, current

    def current_regime(self) -> str | None:
        try:
            return bt.REGIME_NAMES.get(self.regime_info()[1])
        except Exception:
            return None

    # ---- heavy work runs in a separate process so it never blocks the scan loop ------------------
    def _run(self, series: list[bt.Series], **kw) -> bt.Result:
        if self.s.backtest_workers > 0:
            try:
                with self._lock:
                    if self._pool is None:
                        self._pool = ProcessPoolExecutor(max_workers=self.s.backtest_workers, mp_context=get_context("spawn"))
                    pool = self._pool
                return pool.submit(bt.run, series, **kw).result()
            except BrokenProcessPool:
                log.warning("backtest worker died; running in-process")
                with self._lock:
                    self._pool = None
            except Exception as e:
                log.warning("backtest worker failed (%s); running in-process", e)
        return bt.run(series, **kw)

    def shutdown(self) -> None:
        with self._lock:
            pool, self._pool = self._pool, None
        if pool:
            pool.shutdown(wait=False, cancel_futures=True)

    def peers(self, symbol: str) -> list[str]:
        sector = sector_of(symbol)
        same = [x for x in self.universe if x != symbol and sector_of(x) == sector]
        others = sorted((x for x in self.universe if x != symbol and x not in same),
                        key=lambda x: FUNDAMENTALS[x].market_cap if x in FUNDAMENTALS else 0, reverse=True)
        return [symbol, *(same + others)][: self.s.backtest_basket]

    # ---- one trade ---------------------------------------------------------------------------
    def _core(self, symbol: str, setup: str, vals: dict, ttl: float = 300) -> dict:
        """The part of a trade's backtest that does not depend on the live price: which variant won and how it
        held up. Cached by stock, setup, which filters the live trade passes and the market regime, so the
        nightly precompute can fill it and a trade found during the day gets an instant answer."""
        applicable = tuple((vals["rvol"] >= rv, vals["rsi"] < cap) for rv, cap in bt.FILTERS)
        regime = self.regime_info()[1]
        key = (symbol, setup, applicable, regime)
        with self._lock:
            hit = self._core_cache.get(key)
        if hit and time.time() - hit[0] < hit[1].get("_ttl", ttl):
            return {**hit[1], "cached": True}
        started = time.monotonic()
        basket = self.peers(symbol)
        series = [self.series(x) for x in basket]
        res = self._run(series, setups=[setup], slip_bps=self.s.backtest_slip_bps, criteria=self.criteria,
                        applicable={"setup": setup, "rvol": vals["rvol"], "rsi": vals["rsi"]}, top=10, current_regime=regime)
        out = compact(res)
        out.update({"setup": setup, "setup_description": bt.SETUPS[setup], "basket": basket,
                    "ms": int((time.monotonic() - started) * 1000), "source": self.history.name,
                    "at": datetime.now(UTC).isoformat(), "_ttl": ttl})
        with self._lock:
            self._core_cache[key] = (time.time(), out)
        return out

    def for_trade(self, symbol: str, minute_bars: list[Bar]) -> dict:
        bars5 = aggregate(minute_bars, 5)
        if bars5 and minute_bars and minute_bars[-1].ts < bars5[-1].ts + timedelta(minutes=4):
            bars5 = bars5[:-1]  # the newest 5-minute candle is still forming: classify on finished candles, like the backtest
        live = live_series(symbol, bars5)
        if len(live.c) < 25:
            return {"verdict": "not_enough_data", "reasons": ["not enough live bars to classify the setup"], "variants_tested": 0}
        ind = bt.indicators(live)
        setup, vals = bt.live_setup(live, ind)
        note = None
        if setup is None:
            setup, note = "momentum", "no clean setup on the latest bar, so the trade was tested as a momentum entry"
        vals["price"] = float(minute_bars[-1].c)  # the setup is judged on finished candles, the plan is priced at the live price
        out = {k: v for k, v in self._core(symbol, setup, vals).items() if k != "_ttl"}
        out.update({"live": vals, "note": note})
        if out.get("best"):
            v = out["best"]["variant"]
            price = vals["price"]
            r = bt.risk_size(v["stop_atr"] * vals["atr"], price)  # same floor/ceiling as the simulation
            out["tuned_plan"] = {  # rebuilt from the live price and ATR every time, even when the test itself was cached
                "entry": round(price, 2), "stop": round(price - r, 2),
                "target": round(price + v["target_r"] * r, 2),
                "max_hold_min": None if v["max_hold"] >= 999 else v["max_hold"] * 5, "trail": v["trail"],
                "expected_r": round(out["best"]["oos"]["exp_r"], 3), "variant": out["best"]["key"],
            }
        return out

    # ---- nightly precompute: every stock x setup x filter pattern, so intraday verdicts are instant ----------
    def precompute(self, symbols: list[str] | None = None, budget_seconds: float = 1500) -> dict:
        started = time.monotonic()
        syms = symbols or self.universe
        st = {"status": "running", "started_at": datetime.now(UTC).isoformat(), "done": 0, "total": 0, "regime": self.current_regime()}
        self.precompute_status = st
        patterns = [{"rvol": rv, "rsi": rsi} for rv in (1.2, 1.7, 2.5) for rsi in (60.0, 75.0, 90.0)]
        jobs = [(sym, setup, p) for sym in syms for setup in bt.SETUPS for p in patterns]
        st["total"] = len(jobs)
        try:
            for sym, setup, p in jobs:
                if time.monotonic() - started > budget_seconds:
                    st["note"] = "stopped at the time budget"
                    break
                self._core(sym, setup, p, ttl=26 * 3600)
                st["done"] += 1
            st["status"] = "done"
        except Exception as e:
            log.exception("precompute failed")
            st["status"], st["error"] = "failed", f"{type(e).__name__}: {e}"
        st["seconds"] = round(time.monotonic() - started, 1)
        st["finished_at"] = datetime.now(UTC).isoformat()
        return st

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
                res = self._run(series, setups=job["setups"], slip_bps=self.s.backtest_slip_bps, criteria=self.criteria, top=40,
                                current_regime=self.regime_info(job["days"])[1])
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
    d["regime_now"] = d.get("regime", {}).get("current")
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
