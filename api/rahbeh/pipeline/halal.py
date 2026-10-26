"""Halal screen (AAOIFI-style). Business-activity screen first, then financial ratios.

This is a screening aid, not a fatwa. Users who rely on it should confirm with a
qualified Shariah board; the thresholds below are the commonly used AAOIFI ones.
"""

from dataclasses import dataclass, field

from ..market.base import Fundamentals

PROHIBITED_TAGS = {
    "conventional_finance": "conventional banking / interest-based finance",
    "insurance": "conventional insurance",
    "alcohol": "alcohol",
    "tobacco": "tobacco",
    "gambling": "gambling",
    "pork": "pork products",
    "adult": "adult entertainment",
    "weapons": "weapons and defense",
}
PROHIBITED_INDUSTRY_WORDS = ("bank", "insurance", "alcohol", "brewer", "distiller", "winer", "tobacco", "casino", "gambling", "betting",
                             "lottery", "weapon", "firearm", "ammunition", "defense", "pork", "adult entertainment", "cannabis")
MAX_DEBT_TO_MCAP = 0.30
MAX_CASH_TO_MCAP = 0.30


@dataclass
class HalalResult:
    passes: bool
    reasons: list[str] = field(default_factory=list)
    debt_ratio: float | None = None
    cash_ratio: float | None = None


def screen(f: Fundamentals | None) -> HalalResult:
    if f is None:
        return HalalResult(False, ["no company data, so we can't confirm it is halal"])
    reasons = [f"business: {PROHIBITED_TAGS[t]}" for t in f.business_tags if t in PROHIBITED_TAGS]
    ind = f.industry.lower()
    if not reasons and any(w in ind for w in PROHIBITED_INDUSTRY_WORDS):
        reasons.append(f"industry: {f.industry}")
    debt_ratio = cash_ratio = None
    if f.market_cap > 0:
        debt_ratio = f.total_debt / f.market_cap
        cash_ratio = f.cash / f.market_cap
        if debt_ratio > MAX_DEBT_TO_MCAP:
            reasons.append(f"debt is {debt_ratio:.0%} of market value (limit {MAX_DEBT_TO_MCAP:.0%})")
        if cash_ratio > MAX_CASH_TO_MCAP:
            reasons.append(f"cash and interest-bearing holdings are {cash_ratio:.0%} of market value (limit {MAX_CASH_TO_MCAP:.0%})")
    else:
        reasons.append("market value unknown")
    return HalalResult(not reasons, reasons, debt_ratio, cash_ratio)
