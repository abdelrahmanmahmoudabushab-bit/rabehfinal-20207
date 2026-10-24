"""Market mood: says when to be careful. Plain rules over VIX, the S&P 500's move, breadth and the economic
calendar. The risk engine uses the level: calm = normal size, careful = half size, stormy = no new trades."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from ..market.extras import MoodInputs

MULTIPLIER = {"calm": 1.0, "careful": 0.5, "stormy": 0.0}


@dataclass
class Mood:
    level: str  # calm | careful | stormy
    risk_multiplier: float
    reasons: list[str] = field(default_factory=list)
    spy_change_pct: float = 0.0
    breadth_pct: float = 50.0  # share of watched stocks up on the day
    vix: float | None = None
    vix_change: float | None = None
    fed_funds: float | None = None
    ten_year: float | None = None
    ten_year_change_bp: float | None = None
    oil: float | None = None
    oil_change_pct: float | None = None
    events: list[dict] = field(default_factory=list)
    next_event: dict | None = None
    summary: str = ""
    source: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def assess(inp: MoodInputs, spy_change_pct: float, breadth_pct: float, now: datetime) -> Mood:
    reasons: list[str] = []
    level = 0  # 0 calm, 1 careful, 2 stormy

    def bump(to: int, why: str):
        nonlocal level
        level = max(level, to)
        reasons.append(why)

    if inp.vix is not None:
        if inp.vix >= 30:
            bump(2, f"VIX {inp.vix:.1f} — fear is high")
        elif inp.vix >= 22:
            bump(1, f"VIX {inp.vix:.1f} — above normal")
        if inp.vix_prev and inp.vix / inp.vix_prev - 1 >= 0.15:
            bump(1, f"VIX jumped {(inp.vix / inp.vix_prev - 1):.0%}")
    if spy_change_pct <= -2:
        bump(2, f"S&P 500 down {spy_change_pct:.1f}% today")
    elif spy_change_pct <= -1:
        bump(1, f"S&P 500 down {spy_change_pct:.1f}% today")
    if breadth_pct < 25:
        bump(1, f"only {breadth_pct:.0f}% of stocks are up")
    if inp.ten_year is not None and inp.ten_year_prev is not None and abs(inp.ten_year - inp.ten_year_prev) >= 0.15:
        bump(1, f"10-year yield moved {(inp.ten_year - inp.ten_year_prev) * 100:+.0f}bp")

    events = sorted(inp.events, key=lambda e: e.time)
    upcoming = [e for e in events if datetime.fromisoformat(e.time) >= now - timedelta(minutes=15)]
    nxt = next((e for e in upcoming if e.impact == "high"), upcoming[0] if upcoming else None)
    for e in upcoming:
        if e.impact != "high":
            continue
        t = datetime.fromisoformat(e.time)
        if now - timedelta(minutes=15) <= t <= now + timedelta(minutes=60):
            bump(1, f"high-impact event: {e.event} at {t.strftime('%H:%M UTC')}")

    lv = ["calm", "careful", "stormy"][level]
    if not reasons:
        reasons.append("no warning signs")
    summary = {
        "calm": "Normal conditions. Full position sizes.",
        "careful": "Be careful: position sizes are halved until conditions settle.",
        "stormy": "Stormy: no new trades. Open positions keep their stops.",
    }[lv]
    return Mood(
        level=lv, risk_multiplier=MULTIPLIER[lv], reasons=reasons, spy_change_pct=round(spy_change_pct, 2),
        breadth_pct=round(breadth_pct, 1), vix=inp.vix,
        vix_change=round(inp.vix - inp.vix_prev, 2) if inp.vix is not None and inp.vix_prev is not None else None,
        fed_funds=inp.fed_funds, ten_year=inp.ten_year,
        ten_year_change_bp=round((inp.ten_year - inp.ten_year_prev) * 100, 1) if inp.ten_year is not None and inp.ten_year_prev is not None else None,
        oil=inp.oil, oil_change_pct=round((inp.oil / inp.oil_prev - 1) * 100, 2) if inp.oil and inp.oil_prev else None,
        events=[asdict(e) for e in events], next_event=asdict(nxt) if nxt else None, summary=summary, source=inp.source,
    )
