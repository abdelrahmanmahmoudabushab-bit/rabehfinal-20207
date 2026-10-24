"""Shared market data types and the provider interface."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class Bar:
    ts: datetime
    o: float
    h: float
    l: float  # noqa: E741
    c: float
    v: float


@dataclass
class Quote:
    symbol: str
    price: float
    ts: datetime
    source: str


@dataclass
class NewsItem:
    id: str
    headline: str
    source: str
    published_at: datetime  # when it became public, not when we fetched it
    symbols: list[str] = field(default_factory=list)
    url: str = ""
    official: bool = False  # company filing / press release outranks articles


@dataclass
class Fundamentals:
    symbol: str
    name: str
    sector: str
    industry: str
    market_cap: float  # USD
    revenue: float  # trailing twelve months, USD
    net_income: float
    total_debt: float
    cash: float
    next_earnings: str | None = None  # ISO date
    business_tags: list[str] = field(default_factory=list)  # e.g. ["alcohol"], used by the halal filter


TIMEFRAMES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1D": 1440}


def aggregate(bars: list[Bar], minutes: int) -> list[Bar]:
    """Roll 1-minute bars up into N-minute candles (bucketed on the clock, like a charting platform)."""
    if minutes <= 1:
        return list(bars)
    out: list[Bar] = []
    span = minutes * 60
    for b in bars:
        bucket = int(b.ts.timestamp()) // span * span
        if out and int(out[-1].ts.timestamp()) == bucket:
            o = out[-1]
            out[-1] = Bar(o.ts, o.o, max(o.h, b.h), min(o.l, b.l), b.c, o.v + b.v)
        else:
            out.append(Bar(datetime.fromtimestamp(bucket, b.ts.tzinfo), b.o, b.h, b.l, b.c, b.v))
    return out


class MarketData(Protocol):
    name: str

    def now(self) -> datetime: ...
    def is_open(self) -> bool: ...
    def universe(self) -> list[str]: ...
    def minute_bars(self, symbol: str, limit: int = 120) -> list[Bar]: ...
    def daily_bars(self, symbol: str, limit: int = 60) -> list[Bar]: ...
    def quote(self, symbol: str) -> Quote | None: ...
    def second_quote(self, symbol: str) -> Quote | None: ...
    def news(self, symbols: list[str] | None = None, limit: int = 50) -> list[NewsItem]: ...
    def fundamentals(self, symbol: str) -> Fundamentals | None: ...
    def history(self, symbol: str, timeframe: str, limit: int = 400) -> list[Bar]: ...
