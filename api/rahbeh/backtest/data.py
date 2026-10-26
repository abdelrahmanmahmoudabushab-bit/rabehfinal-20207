"""History for the backtester: 5-minute regular-session bars.

- AlpacaHistory: real bars (split/dividend adjusted) from Alpaca, cached in our own database so a backtest
  can be replayed and checked later.
- SimHistory: simulated sessions for the demo market. A backtest on these says nothing about the real
  market; it shows how the tool works.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import select

from ..db import HistBar, SessionLocal
from ..market.universe import FUNDAMENTALS, START_PRICES
from .engine import BARS_PER_DAY, Series

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def trading_days(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def to_series(symbol: str, rows: list[tuple[datetime, float, float, float, float, float]]) -> Series:
    """Keep regular-session bars only and index them by session and bar-of-day."""
    keep = []
    for ts, o, h, lo, c, v in rows:
        et = ts.astimezone(ET)
        mins = et.hour * 60 + et.minute - (9 * 60 + 30)
        if 0 <= mins < 390:
            keep.append((ts, et.date(), mins // 5, o, h, lo, c, v))
    keep.sort(key=lambda r: r[0])
    days = sorted({r[1] for r in keep})
    di = {d: i for i, d in enumerate(days)}
    arr = lambda j: np.array([r[j] for r in keep], dtype=float)  # noqa: E731
    return Series(symbol, np.array([int(r[0].timestamp()) for r in keep], dtype=np.int64), arr(3), arr(4), arr(5), arr(6), arr(7),
                  np.array([di[r[1]] for r in keep], dtype=np.int64), np.array([r[2] for r in keep], dtype=np.int64))


class SimHistory:
    name = "simulated"

    def __init__(self, end: date | None = None):
        pinned = os.environ.get("SIM_HISTORY_END")  # tests pin this so simulated history does not change with the date
        self.end = end or (date.fromisoformat(pinned) if pinned else datetime.now(ET).date() - timedelta(days=1))

    def series(self, symbol: str, days: int = 60) -> Series:
        seed = int(hashlib.md5(f"hist|{symbol}|{self.end}".encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        price = START_PRICES.get(symbol, 100.0)
        f = FUNDAMENTALS.get(symbol)
        base_vol = max(2_000.0, (f.market_cap if f else 5e11) / 1e8) * 5
        u_shape = 1 + 1.6 * (np.linspace(-1, 1, BARS_PER_DAY) ** 2)
        rows = []
        for d in trading_days(self.end, days):
            price *= 1 + rng.normal(0, 0.012)  # overnight gap
            drift, left = 0.0, 0
            for b in range(BARS_PER_DAY):
                if left == 0 and rng.random() < 0.02:  # a news burst, up or down with equal odds: drift + volume for a while
                    drift, left = rng.choice([-1, 1]) * abs(rng.normal(0.0008, 0.0006)), int(rng.integers(4, 14))
                d_now = drift if left > 0 else 0.0
                left = max(0, left - 1)
                o = price
                c = max(1.0, o * (1 + d_now + rng.normal(0, 0.0022)))
                h = max(o, c) * (1 + abs(rng.normal(0, 0.0009)))
                lo = min(o, c) * (1 - abs(rng.normal(0, 0.0009)))
                v = base_vol * u_shape[b] * rng.uniform(0.6, 1.4) * (3.5 if d_now else 1.0)
                ts = datetime.combine(d, time(9, 30), ET) + timedelta(minutes=5 * b)
                rows.append((ts.astimezone(UTC), o, h, lo, c, v))
                price = c
        return to_series(symbol, rows)


class AlpacaHistory:
    name = "alpaca"

    def __init__(self, settings):
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.historical import StockHistoricalDataClient

        self.client = StockHistoricalDataClient(settings.alpaca_api_key, settings.alpaca_secret_key)
        self.feed = DataFeed.SIP if settings.alpaca_data_feed.lower() == "sip" else DataFeed.IEX
        self.adjustment = Adjustment.ALL

    def series(self, symbol: str, days: int = 60) -> Series:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        start = datetime.combine(trading_days(datetime.now(ET).date(), days)[0], time(0), ET).astimezone(UTC)
        with SessionLocal() as db:
            cached = db.scalars(select(HistBar).where(HistBar.symbol == symbol, HistBar.tf == "5m", HistBar.ts >= start)
                                .order_by(HistBar.ts)).all()
            rows = [(b.ts if b.ts.tzinfo else b.ts.replace(tzinfo=UTC), b.o, b.h, b.l, b.c, b.v) for b in cached]
        fetch_from = (rows[-1][0] + timedelta(minutes=5)) if rows else start
        if datetime.now(UTC) - fetch_from > timedelta(minutes=10):
            try:
                bs = self.client.get_stock_bars(StockBarsRequest(
                    symbol_or_symbols=symbol, timeframe=TimeFrame(5, TimeFrameUnit.Minute), start=fetch_from,
                    feed=self.feed, adjustment=self.adjustment,
                ))
                new = [(r.timestamp, r.open, r.high, r.low, r.close, r.volume) for r in bs.data.get(symbol, [])]
                with SessionLocal() as db:
                    for ts, o, h, lo, c, v in new:
                        db.merge(HistBar(symbol=symbol, tf="5m", ts=ts, o=o, h=h, l=lo, c=c, v=v))
                    db.commit()
                rows += new
            except Exception as e:
                log.warning("history fetch failed for %s: %s", symbol, e)
        return to_series(symbol, rows)
