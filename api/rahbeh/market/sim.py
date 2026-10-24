"""A seeded market simulator so the whole app is usable without any API keys.

Prices follow a random walk with intraday volume, and the simulator injects news headlines
that push the stock's drift and volume, so the scanner has real-looking movers to find.
It also injects rare data faults (stale prints, a bad second-source price) so the data
checks visibly do their job.
"""

import random
import threading
import uuid
from datetime import UTC, datetime, timedelta

from .base import Bar, Fundamentals, NewsItem, Quote
from .universe import BENCHMARK, FUNDAMENTALS, START_PRICES, SYMBOLS

_GOOD = [
    "{name} beats quarterly earnings estimates and raises full-year guidance",
    "{name} announces $10B share buyback program",
    "{name} wins major multi-year contract",
    "Analyst upgrades {name} to Buy, citing strong demand",
    "{name} unveils new product line ahead of schedule",
    "{name} reports record quarterly revenue",
]
_BAD = [
    "{name} misses revenue estimates and cuts outlook",
    "{name} faces regulatory probe over business practices",
    "Analyst downgrades {name} to Sell on slowing growth",
    "{name} recalls products after safety concerns",
    "{name} CFO resigns unexpectedly",
]
_MARKET = [
    ("Fed holds rates steady, signals patience on cuts", 0),
    ("Oil climbs as supply concerns grow", 0),
    ("US jobs report comes in stronger than expected", 1),
    ("Treasury yields jump after hot inflation print", -1),
]


class SimMarket:
    name = "simulator"

    def __init__(self, seed: int = 7, history_minutes: int = 240, always_open: bool = True):
        self._rng = random.Random(seed)
        self._lock = threading.RLock()
        self.always_open = always_open
        start = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=history_minutes)
        self._clock = start
        self._bars: dict[str, list[Bar]] = {}
        self._daily: dict[str, list[Bar]] = {}
        self._drift: dict[str, tuple[float, int]] = {}  # symbol -> (per-minute drift, minutes left)
        self._news: list[NewsItem] = []
        self._faults: dict[str, str] = {}
        for sym in [*SYMBOLS, BENCHMARK]:
            p = START_PRICES[sym]
            self._daily[sym] = self._make_daily(p)
            self._bars[sym] = [Bar(start, p, p, p, p, self._base_volume(sym))]
        for _ in range(history_minutes):
            self.tick()

    # ---- simulation -------------------------------------------------------------------
    def _base_volume(self, sym: str) -> float:
        f = FUNDAMENTALS.get(sym)
        cap = f.market_cap if f else 5e11
        return max(2_000.0, cap / 1e8)

    def _make_daily(self, last: float, days: int = 250) -> list[Bar]:
        prices = [last]
        for _ in range(days - 1):
            prices.append(prices[-1] / (1 + self._rng.gauss(0.0004, 0.017)))
        prices.reverse()
        yesterday = datetime.now(UTC).replace(hour=20, minute=0, second=0, microsecond=0) - timedelta(days=1)
        out = []
        for i, c in enumerate(prices):
            o = c * (1 + self._rng.gauss(0, 0.006))
            out.append(Bar(yesterday - timedelta(days=days - 1 - i), o, max(o, c) * 1.008, min(o, c) * 0.992, c, 1e6))
        return out

    def tick(self) -> None:
        """Advance the simulated market by one minute."""
        with self._lock:
            self._clock += timedelta(minutes=1)
            if self._rng.random() < 0.18:
                self._inject_news()
            market_mood = self._rng.gauss(0, 0.00025)
            for sym, bars in self._bars.items():
                last = bars[-1].c
                drift, left = self._drift.get(sym, (0.0, 0))
                if left > 0:
                    self._drift[sym] = (drift, left - 1)
                else:
                    drift = 0.0
                beta = 1.0 if sym != BENCHMARK else 0.8
                ret = beta * market_mood + drift + self._rng.gauss(0, 0.0008 if sym != BENCHMARK else 0.0003)
                c = max(1.0, last * (1 + ret))
                o = last
                h = max(o, c) * (1 + abs(self._rng.gauss(0, 0.0004)))
                lo = min(o, c) * (1 - abs(self._rng.gauss(0, 0.0004)))
                vol = self._base_volume(sym) * self._rng.uniform(0.6, 1.4) * (4.0 if left > 0 else 1.0)
                bars.append(Bar(self._clock, o, h, lo, c, vol))
                if len(bars) > 2000:
                    del bars[:500]
            # rare data faults so the checks have something to catch
            self._faults.clear()
            if self._rng.random() < 0.05:
                self._faults[self._rng.choice(SYMBOLS)] = self._rng.choice(["bad_second_source", "zero_volume"])

    def _inject_news(self) -> None:
        if self._rng.random() < 0.15:
            headline, _ = self._rng.choice(_MARKET)
            self._news.append(NewsItem(str(uuid.uuid4()), headline, "SimWire", self._clock, []))
            return
        sym = self._rng.choice(SYMBOLS)
        good = self._rng.random() < 0.6
        name = FUNDAMENTALS[sym].name
        headline = self._rng.choice(_GOOD if good else _BAD).format(name=name)
        official = "announces" in headline or "reports" in headline
        self._news.append(NewsItem(str(uuid.uuid4()), headline, "SimWire", self._clock, [sym], official=official))
        strength = self._rng.uniform(0.0003, 0.0008)
        self._drift[sym] = (strength if good else -strength, self._rng.randint(20, 50))
        if len(self._news) > 400:
            del self._news[:100]

    # ---- MarketData interface -------------------------------------------------------
    def now(self) -> datetime:
        return self._clock

    def is_open(self) -> bool:
        return True if self.always_open else _us_session_open(self._clock)

    def universe(self) -> list[str]:
        return list(SYMBOLS)

    def minute_bars(self, symbol: str, limit: int = 120) -> list[Bar]:
        with self._lock:
            bars = list(self._bars.get(symbol, [])[-limit:])
        if self._faults.get(symbol) == "zero_volume" and bars:
            b = bars[-1]
            bars[-1] = Bar(b.ts, b.o, b.h, b.l, b.c, 0.0)
        return bars

    def daily_bars(self, symbol: str, limit: int = 60) -> list[Bar]:
        return list(self._daily.get(symbol, [])[-limit:])

    def quote(self, symbol: str) -> Quote | None:
        bars = self._bars.get(symbol)
        return Quote(symbol, bars[-1].c, bars[-1].ts, "sim-primary") if bars else None

    def second_quote(self, symbol: str) -> Quote | None:
        q = self.quote(symbol)
        if not q:
            return None
        gap = 0.03 if self._faults.get(symbol) == "bad_second_source" else self._rng.gauss(0, 0.0002)
        return Quote(symbol, q.price * (1 + gap), q.ts, "sim-secondary")

    def news(self, symbols: list[str] | None = None, limit: int = 50) -> list[NewsItem]:
        with self._lock:
            items = [n for n in self._news if not symbols or not n.symbols or set(n.symbols) & set(symbols)]
        return list(reversed(items[-limit:]))

    def fundamentals(self, symbol: str) -> Fundamentals | None:
        return FUNDAMENTALS.get(symbol)


def _us_session_open(ts: datetime) -> bool:
    from zoneinfo import ZoneInfo

    et = ts.astimezone(ZoneInfo("America/New_York"))
    if et.weekday() >= 5:
        return False
    minutes = et.hour * 60 + et.minute
    return 9 * 60 + 30 <= minutes < 16 * 60
