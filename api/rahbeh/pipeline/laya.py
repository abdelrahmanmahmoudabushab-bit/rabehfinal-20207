"""LAYA — the fast, free pre-filter in front of the Claude agents.

It answers four quick questions per stock: is the news bullish or bearish, is it about this
company or the whole market, (halal is handled in halal.py), and is the stock worth a look at
all. Only "yes" stocks reach the paid agents. This version is a transparent lexicon + rules
model with no external calls; swap `score_headline` for an open-source sentiment model
(e.g. FinBERT) without touching the rest of the pipeline.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..market.base import NewsItem
from .features import Features

_POS = {
    "beat": 2, "beats": 2, "raises": 2, "raised": 2, "record": 2, "upgrade": 2, "upgrades": 2,
    "buyback": 2, "wins": 1.5, "surge": 1.5, "soars": 2, "strong": 1, "growth": 1, "approval": 2,
    "approved": 2, "partnership": 1, "contract": 1, "outperform": 1.5, "unveils": 1, "launch": 1,
    "ahead": 1, "profit": 1, "dividend": 1,
}
_NEG = {
    "miss": -2, "misses": -2, "cuts": -2, "cut": -1.5, "downgrade": -2, "downgrades": -2, "probe": -2,
    "lawsuit": -2, "recall": -2, "recalls": -2, "resigns": -1.5, "plunge": -2, "falls": -1, "weak": -1,
    "slowing": -1, "loss": -1, "warning": -1.5, "investigation": -2, "fraud": -3, "bankruptcy": -3,
    "layoffs": -1, "delay": -1, "halted": -2,
}
_WORD = re.compile(r"[a-z]+")


@dataclass
class LayaResult:
    worth_a_look: bool
    score: float  # ranking score for picking the top candidates
    sentiment: float  # -1..1 across this stock's recent headlines
    company_news: bool
    headlines: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def score_headline(text: str) -> float:
    words = _WORD.findall(text.lower())
    raw = sum(_POS.get(w, 0) + _NEG.get(w, 0) for w in words)
    return max(-1.0, min(1.0, raw / 3))


def dedupe(news: list[NewsItem]) -> list[NewsItem]:
    """The same story copied by 20 sites counts once."""
    seen: set[str] = set()
    out = []
    for n in news:
        key = " ".join(sorted(set(_WORD.findall(n.headline.lower())))[:12])
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def evaluate(symbol: str, f: Features, news: list[NewsItem], now: datetime, lookback_min: int = 90) -> LayaResult:
    recent = [n for n in dedupe(news) if symbol in n.symbols and now - n.published_at <= timedelta(minutes=lookback_min)]
    heads = []
    for n in recent[:5]:
        s = score_headline(n.headline) * (1.5 if n.official else 1.0)
        heads.append({"headline": n.headline, "source": n.source, "at": n.published_at.isoformat(),
                      "sentiment": round(max(-1, min(1, s)), 2), "official": n.official})
    sentiment = sum(h["sentiment"] for h in heads) / len(heads) if heads else 0.0

    reasons = []
    if heads:
        reasons.append(f"{len(heads)} company headline(s), sentiment {sentiment:+.2f}")
    if f.volume_ratio >= 1.8:
        reasons.append(f"heavy trading ({f.volume_ratio:.1f}x normal volume)")
    if abs(f.change_30m_pct) >= 0.6:
        reasons.append(f"moving {f.change_30m_pct:+.2f}% in 30 min")

    # Long-only MVP: we want bullish setups. Bearish news is a reason to skip, not to short.
    bullish = sentiment > 0.15 or (not heads and f.momentum_score > 25)
    active = f.volume_ratio >= 1.5 or abs(f.change_30m_pct) >= 0.6 or bool(heads)
    not_extended = f.rsi14 < 82
    worth = bullish and active and not_extended and f.trend != "down"
    if not not_extended:
        reasons.append(f"too stretched (RSI {f.rsi14:.0f})")
    if sentiment < -0.15:
        reasons.append("bearish news")

    score = max(0.0, f.momentum_score) + sentiment * 40 + min(f.volume_ratio, 4) * 8
    return LayaResult(worth, round(score, 1), round(sentiment, 2), bool(heads), heads, reasons)
