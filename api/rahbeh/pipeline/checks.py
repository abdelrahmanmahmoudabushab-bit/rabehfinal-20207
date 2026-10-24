"""Step 1 — "Data OK?". Plain code, runs before any agent sees a number."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..market.base import Bar, Quote

MAX_SOURCE_GAP = 0.005  # 0.5% between broker feed and second provider pauses the stock
MAX_STALE = timedelta(minutes=5)
MAX_MINUTE_JUMP = 0.08  # an 8% move in one minute without news is treated as a bad print
MIN_BARS = 30


@dataclass
class DataCheck:
    ok: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_data(bars: list[Bar], quote: Quote | None, second: Quote | None, now: datetime) -> DataCheck:
    problems: list[str] = []
    warnings: list[str] = []

    if quote is None:
        return DataCheck(False, ["no live price"])
    if len(bars) < MIN_BARS:
        problems.append(f"only {len(bars)} minute bars (need {MIN_BARS})")

    if now - quote.ts > MAX_STALE:
        problems.append(f"price is stale ({int((now - quote.ts).total_seconds() // 60)} min old)")

    if bars:
        last = bars[-1]
        if last.v <= 0:
            problems.append("zero volume on the latest bar")
        recent = bars[-30:]
        gaps = sum(1 for a, b in zip(recent, recent[1:]) if (b.ts - a.ts) > timedelta(minutes=3))
        if gaps >= 3:
            problems.append(f"{gaps} gaps of missing minutes in the last 30 bars")
        for a, b in zip(recent, recent[1:]):
            if a.c > 0 and abs(b.c / a.c - 1) > MAX_MINUTE_JUMP:
                problems.append(f"impossible jump {a.c:.2f} → {b.c:.2f} at {b.ts:%H:%M}")
                break
        if any(b.h < b.l or b.c <= 0 for b in recent):
            problems.append("malformed bar (high below low or non-positive price)")

    if second is None:
        warnings.append("single price source (no second provider configured)")
    elif quote.price > 0:
        gap = abs(second.price / quote.price - 1)
        if gap > MAX_SOURCE_GAP:
            problems.append(f"sources disagree by {gap:.2%} ({quote.source} {quote.price:.2f} vs {second.source} {second.price:.2f})")

    return DataCheck(not problems, problems, warnings)
