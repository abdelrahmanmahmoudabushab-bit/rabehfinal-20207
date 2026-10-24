"""Feature scores, calculated in code. The agents read these numbers; they never compute them."""

from dataclasses import asdict, dataclass
from statistics import mean, pstdev

from ..market.base import Bar


@dataclass
class Features:
    price: float
    change_day_pct: float  # vs previous daily close
    change_30m_pct: float
    change_5m_pct: float
    rsi14: float
    vwap: float
    above_vwap: bool
    ema9: float
    ema21: float
    trend: str  # up | down | flat
    volume_ratio: float  # last 15 min volume vs the session's average 15 min
    atr14: float  # minute ATR
    day_high: float
    day_low: float
    daily_trend_20d_pct: float
    volatility_20d_pct: float
    momentum_score: float  # -100..100 summary used by LAYA

    def to_dict(self) -> dict:
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in asdict(self).items()}


def ema(values: list[float], n: int) -> float:
    if not values:
        return 0.0
    k = 2 / (n + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes: list[float], n: int = 14) -> float:
    if len(closes) <= n:
        return 50.0
    gains, losses = [], []
    for a, b in zip(closes[-n - 1:], closes[-n:]):
        d = b - a
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain, avg_loss = mean(gains), mean(losses)
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def atr(bars: list[Bar], n: int = 14) -> float:
    if len(bars) < 2:
        return 0.0
    trs = [max(b.h - b.l, abs(b.h - a.c), abs(b.l - a.c)) for a, b in zip(bars, bars[1:])]
    return mean(trs[-n:])


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else 0.0


def compute(minute: list[Bar], daily: list[Bar]) -> Features:
    closes = [b.c for b in minute]
    price = closes[-1]
    # previous session's close: the last daily bar from before today (live feeds include today's partial bar)
    earlier = [b for b in daily if b.ts.date() < minute[-1].ts.date()]
    prev_close = earlier[-1].c if earlier else minute[0].o
    vol_total = sum(b.v for b in minute) or 1
    vwap = sum(((b.h + b.l + b.c) / 3) * b.v for b in minute) / vol_total
    e9, e21 = ema(closes, 9), ema(closes, 21)
    trend = "up" if e9 > e21 * 1.0005 and price > vwap else "down" if e9 < e21 * 0.9995 and price < vwap else "flat"
    chunks = [sum(b.v for b in minute[i:i + 15]) for i in range(0, len(minute), 15)]
    avg_chunk = mean(chunks[:-1]) if len(chunks) > 1 else chunks[0]
    last15 = sum(b.v for b in minute[-15:])
    volume_ratio = last15 / avg_chunk if avg_chunk else 1.0
    dcl = [b.c for b in daily]
    rets = [_pct(b, a) for a, b in zip(dcl, dcl[1:])][-20:]
    r = rsi(closes)
    ch30 = _pct(price, closes[-31]) if len(closes) > 30 else _pct(price, closes[0])
    ch5 = _pct(price, closes[-6]) if len(closes) > 5 else 0.0

    # Momentum score: blend of short-term move, trend alignment and volume, clipped to ±100
    m = ch30 * 25 + ch5 * 40 + (15 if trend == "up" else -15 if trend == "down" else 0)
    m *= min(2.0, max(0.5, volume_ratio))
    momentum = max(-100.0, min(100.0, m))

    return Features(
        price=price, change_day_pct=_pct(price, prev_close), change_30m_pct=ch30, change_5m_pct=ch5,
        rsi14=r, vwap=vwap, above_vwap=price > vwap, ema9=e9, ema21=e21, trend=trend,
        volume_ratio=volume_ratio, atr14=atr(minute), day_high=max(b.h for b in minute),
        day_low=min(b.l for b in minute),
        daily_trend_20d_pct=_pct(dcl[-1], dcl[-21]) if len(dcl) > 21 else 0.0,
        volatility_20d_pct=pstdev(rets) if len(rets) > 2 else 0.0, momentum_score=momentum,
    )
