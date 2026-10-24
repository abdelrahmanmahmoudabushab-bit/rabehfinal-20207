"""Extra data beyond prices: SEC filings, earnings dates and surprises, analyst ratings, and the
macro inputs for the Market mood agent (VIX, rates, oil, economic calendar).

Live sources (each optional, each cached):
  SEC EDGAR (free, no key)      filings                      www.sec.gov, data.sec.gov
  Finnhub (FINNHUB_API_KEY)     earnings calendar + surprises, analyst recommendation trends, economic calendar
  FRED (FRED_API_KEY, free)     VIX (VIXCLS), Fed funds (DFF), 10-year yield (DGS10), WTI oil (DCOILWTICO)
  FMP (FMP_API_KEY)             economic calendar fallback
The demo market uses SimExtras, which generates clearly-labelled simulated values.
"""

import hashlib
import logging
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

from ..config import Settings
from .base import MarketData

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
FILING_FORMS = {"8-K", "10-Q", "10-K", "20-F", "6-K", "S-1", "4", "SC 13D", "SC 13G", "DEF 14A"}
FORM_LABELS = {
    "8-K": "Current report (material event)",
    "10-Q": "Quarterly report",
    "10-K": "Annual report",
    "20-F": "Annual report (foreign issuer)",
    "6-K": "Current report (foreign issuer)",
    "S-1": "Registration statement",
    "4": "Insider trade",
    "SC 13D": "Activist stake (>5%)",
    "SC 13G": "Passive stake (>5%)",
    "DEF 14A": "Proxy statement",
}


@dataclass
class Filing:
    form: str
    filed: str  # YYYY-MM-DD
    description: str
    url: str = ""


@dataclass
class EarningsInfo:
    next_date: str | None = None  # YYYY-MM-DD
    next_hour: str | None = None  # bmo (before open) | amc (after close) | dmh
    eps_estimate: float | None = None
    history: list[dict] = field(default_factory=list)  # [{period, estimate, actual, surprise_pct}], newest first

    def days_until(self, today: date) -> int | None:
        if not self.next_date:
            return None
        return (date.fromisoformat(self.next_date) - today).days


@dataclass
class Ratings:
    period: str
    strong_buy: int
    buy: int
    hold: int
    sell: int
    strong_sell: int

    @property
    def total(self) -> int:
        return self.strong_buy + self.buy + self.hold + self.sell + self.strong_sell

    @property
    def score(self) -> float | None:
        """1 = strong sell ... 5 = strong buy."""
        if not self.total:
            return None
        return (5 * self.strong_buy + 4 * self.buy + 3 * self.hold + 2 * self.sell + self.strong_sell) / self.total


@dataclass
class MacroEvent:
    time: str  # ISO, UTC
    country: str
    event: str
    impact: str  # high | medium | low
    estimate: str = ""
    previous: str = ""
    actual: str = ""


@dataclass
class MoodInputs:
    vix: float | None = None
    vix_prev: float | None = None
    fed_funds: float | None = None
    ten_year: float | None = None
    ten_year_prev: float | None = None
    oil: float | None = None
    oil_prev: float | None = None
    events: list[MacroEvent] = field(default_factory=list)
    as_of: str = ""
    source: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class Extras(Protocol):
    name: str

    def filings(self, symbol: str, limit: int = 8) -> list[Filing]: ...
    def earnings(self, symbol: str) -> EarningsInfo: ...
    def ratings(self, symbol: str) -> Ratings | None: ...
    def mood_inputs(self) -> MoodInputs: ...
    def sources(self) -> list[dict]: ...


class _Cache:
    def __init__(self):
        self._d: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, ttl: float, fn):
        with self._lock:
            hit = self._d.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        try:
            val = fn()
        except Exception as e:  # keep serving the last good value when a provider hiccups
            log.warning("extras %s failed: %s", key, e)
            if hit:
                return hit[1]
            raise
        with self._lock:
            self._d[key] = (time.time(), val)
        return val


# ---- parsers (pure, unit-tested against the providers' documented shapes) ----------------------
def parse_sec_submissions(data: dict, cik: int, limit: int) -> list[Filing]:
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    out: list[Filing] = []
    for i, form in enumerate(forms):
        if form not in FILING_FORMS:
            continue
        acc = recent["accessionNumber"][i]
        doc = (recent.get("primaryDocument") or [""] * len(forms))[i]
        desc = (recent.get("primaryDocDescription") or [""] * len(forms))[i] or FORM_LABELS.get(form, form)
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}" if doc else ""
        out.append(Filing(form, recent["filingDate"][i], desc, url))
        if len(out) >= limit:
            break
    return out


def parse_finnhub_earnings(calendar: dict, surprises: list, today: date) -> EarningsInfo:
    upcoming = sorted(
        (r for r in calendar.get("earningsCalendar", []) if r.get("date") and r["date"] >= today.isoformat()),
        key=lambda r: r["date"],
    )
    nxt = upcoming[0] if upcoming else {}
    hist = [
        {"period": r.get("period"), "estimate": r.get("estimate"), "actual": r.get("actual"),
         "surprise_pct": r.get("surprisePercent")}
        for r in sorted(surprises or [], key=lambda r: r.get("period", ""), reverse=True)[:4]
    ]
    return EarningsInfo(nxt.get("date"), nxt.get("hour") or None, nxt.get("epsEstimate"), hist)


def parse_finnhub_recommendation(rows: list) -> Ratings | None:
    if not rows:
        return None
    r = max(rows, key=lambda x: x.get("period", ""))
    return Ratings(r.get("period", ""), r.get("strongBuy", 0), r.get("buy", 0), r.get("hold", 0), r.get("sell", 0), r.get("strongSell", 0))


def parse_fred(data: dict) -> tuple[float | None, float | None]:
    """Latest and previous numeric observation (FRED marks missing days with '.')."""
    vals = [float(o["value"]) for o in data.get("observations", []) if o.get("value") not in (None, ".")]
    return (vals[0] if vals else None, vals[1] if len(vals) > 1 else None)


def _impact(v) -> str:
    s = str(v).lower()
    return "high" if s in ("high", "3") else "medium" if s in ("medium", "2") else "low"


def parse_finnhub_economic(data: dict) -> list[MacroEvent]:
    out = []
    for r in data.get("economicCalendar", []):
        t = r.get("time", "")
        try:
            ts = datetime.fromisoformat(t.replace(" ", "T")).replace(tzinfo=UTC).isoformat()
        except ValueError:
            continue
        out.append(MacroEvent(ts, r.get("country", ""), r.get("event", ""), _impact(r.get("impact")),
                              str(r.get("estimate") or ""), str(r.get("prev") or ""), str(r.get("actual") or "")))
    return out


def parse_fmp_economic(rows: list) -> list[MacroEvent]:
    out = []
    for r in rows or []:
        try:
            ts = datetime.fromisoformat(str(r.get("date", "")).replace(" ", "T")).replace(tzinfo=UTC).isoformat()
        except ValueError:
            continue
        out.append(MacroEvent(ts, r.get("country", ""), r.get("event", ""), _impact(r.get("impact")),
                              str(r.get("estimate") or ""), str(r.get("previous") or ""), str(r.get("actual") or "")))
    return out


# ---- live ------------------------------------------------------------------------------------
class LiveExtras:
    name = "live"

    def __init__(self, s: Settings):
        self.s = s
        self.http = httpx.Client(timeout=10, headers={"User-Agent": s.sec_user_agent})
        self.cache = _Cache()

    def _get(self, url: str, **params):
        r = self.http.get(url, params=params)
        r.raise_for_status()
        return r.json()

    def _cik(self, symbol: str) -> int | None:
        table = self.cache.get("sec:tickers", 24 * 3600, lambda: {
            v["ticker"].upper(): int(v["cik_str"]) for v in self._get("https://www.sec.gov/files/company_tickers.json").values()
        })
        return table.get(symbol.upper())

    def filings(self, symbol: str, limit: int = 8) -> list[Filing]:
        def fetch():
            cik = self._cik(symbol)
            if not cik:
                return []
            return parse_sec_submissions(self._get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"), cik, limit)

        try:
            return self.cache.get(f"sec:{symbol}", 3600, fetch)
        except Exception:
            return []

    def earnings(self, symbol: str) -> EarningsInfo:
        if not self.s.finnhub_api_key:
            return EarningsInfo()
        tok = self.s.finnhub_api_key
        today = datetime.now(ET).date()

        def fetch():
            cal = self._get("https://finnhub.io/api/v1/calendar/earnings", symbol=symbol, token=tok,
                            **{"from": today.isoformat(), "to": (today + timedelta(days=100)).isoformat()})
            sur = self._get("https://finnhub.io/api/v1/stock/earnings", symbol=symbol, token=tok)
            return parse_finnhub_earnings(cal, sur, today)

        try:
            return self.cache.get(f"earn:{symbol}", 6 * 3600, fetch)
        except Exception:
            return EarningsInfo()

    def ratings(self, symbol: str) -> Ratings | None:
        if not self.s.finnhub_api_key:
            return None
        try:
            return self.cache.get(f"rec:{symbol}", 12 * 3600, lambda: parse_finnhub_recommendation(
                self._get("https://finnhub.io/api/v1/stock/recommendation", symbol=symbol, token=self.s.finnhub_api_key)))
        except Exception:
            return None

    def mood_inputs(self) -> MoodInputs:
        def fetch():
            m = MoodInputs(as_of=datetime.now(UTC).isoformat(), source="FRED" if self.s.fred_api_key else "")
            if self.s.fred_api_key:
                def series(sid):
                    return parse_fred(self._get("https://api.stlouisfed.org/fred/series/observations", series_id=sid,
                                                api_key=self.s.fred_api_key, file_type="json", sort_order="desc", limit=10))
                m.vix, m.vix_prev = series("VIXCLS")
                m.fed_funds, _ = series("DFF")
                m.ten_year, m.ten_year_prev = series("DGS10")
                m.oil, m.oil_prev = series("DCOILWTICO")
            m.events = self._economic_calendar()
            return m

        try:
            return self.cache.get("mood", 15 * 60, fetch)
        except Exception:
            return MoodInputs(as_of=datetime.now(UTC).isoformat())

    def _economic_calendar(self) -> list[MacroEvent]:
        today = datetime.now(ET).date()
        rng = {"from": today.isoformat(), "to": (today + timedelta(days=2)).isoformat()}
        if self.s.finnhub_api_key:
            try:
                ev = parse_finnhub_economic(self._get("https://finnhub.io/api/v1/calendar/economic", token=self.s.finnhub_api_key, **rng))
                if ev:
                    return [e for e in ev if e.country in ("US", "")]
            except Exception as e:  # premium endpoint on some plans
                log.info("finnhub economic calendar unavailable: %s", e)
        if self.s.fmp_api_key:
            try:
                ev = parse_fmp_economic(self._get("https://financialmodelingprep.com/stable/economic-calendar", apikey=self.s.fmp_api_key, **rng))
                return [e for e in ev if e.country in ("US", "")]
            except Exception as e:
                log.info("fmp economic calendar unavailable: %s", e)
        return []

    def sources(self) -> list[dict]:
        s = self.s
        return [
            _src("Alpaca market data", "Live prices, minute bars, chart candles", "connected" if s.alpaca_api_key else "missing_key", "ALPACA_API_KEY"),
            _src("Alpaca news", "Headlines with publish times", "connected" if s.alpaca_api_key else "missing_key", "ALPACA_API_KEY"),
            _src("Alpaca broker", "Bracket orders, positions, account", "connected" if s.alpaca_api_key else "missing_key", "ALPACA_API_KEY",
                 "paper account" if s.alpaca_paper else "LIVE MONEY"),
            _src("SEC EDGAR", "Company filings (8-K, 10-Q, 10-K, insider Form 4)", "connected", "SEC_USER_AGENT", "free, no key"),
            _src("Finnhub", "Second price source, earnings dates & surprises, analyst ratings, economic calendar",
                 "connected" if s.finnhub_api_key else "missing_key", "FINNHUB_API_KEY"),
            _src("FRED (St. Louis Fed)", "VIX, Fed funds rate, 10-year yield, oil", "connected" if s.fred_api_key else "missing_key", "FRED_API_KEY", "free key"),
            _src("Financial Modeling Prep", "Company fundamentals, economic calendar fallback", "connected" if s.fmp_api_key else "missing_key", "FMP_API_KEY"),
            *_planned(),
        ]


def _src(name: str, provides: str, status: str, env: str, note: str = "") -> dict:
    return {"name": name, "provides": provides, "status": status, "env": env, "note": note}


def _planned() -> list[dict]:
    return [
        _src("Short interest", "Extra signal (plan item 10)", "not_wired", "", "needs a paid feed (e.g. FINRA / vendor)"),
        _src("Unusual options activity", "Extra signal (plan item 11)", "not_wired", "", "needs an options flow feed"),
        _src("Earnings call transcripts", "Deeper company reading (plan item 12)", "not_wired", "", "paid FMP / vendor plan"),
        _src("Gulf & Egypt prices, Arabic news", "Local markets (plan item 13)", "not_wired", "", "needs a regional data vendor"),
    ]


# ---- demo ------------------------------------------------------------------------------------
_SIM_EVENTS = [
    ("08:30", "CPI m/m", "high"), ("08:30", "Initial jobless claims", "medium"), ("10:00", "ISM services PMI", "medium"),
    ("14:00", "FOMC rate decision", "high"), ("10:30", "Crude oil inventories", "low"), ("08:30", "Retail sales m/m", "high"),
]
_SIM_8K = ["Results of operations and financial condition", "Departure of directors or officers", "Entry into a material agreement",
           "Regulation FD disclosure", "Other events"]


class SimExtras:
    """Deterministic, clearly simulated extras for the demo market."""

    name = "simulated"

    def __init__(self, market: MarketData):
        self.market = market

    def _rng(self, *parts) -> random.Random:
        return random.Random(int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:8], 16))

    def _today(self) -> date:
        return self.market.now().astimezone(ET).date()

    def filings(self, symbol: str, limit: int = 8) -> list[Filing]:
        rng = self._rng("filings", symbol, self._today())
        out = []
        for _ in range(rng.randint(3, 7)):
            form = rng.choice(["8-K", "8-K", "4", "4", "10-Q", "SC 13G"])
            desc = rng.choice(_SIM_8K) if form == "8-K" else FORM_LABELS[form]
            out.append(Filing(form, (self._today() - timedelta(days=rng.randint(0, 80))).isoformat(), desc + " (simulated)"))
        return sorted(out, key=lambda f: f.filed, reverse=True)[:limit]

    def earnings(self, symbol: str) -> EarningsInfo:
        rng = self._rng("earn", symbol)
        # a couple of names report tomorrow so the earnings safety check has something to do
        days = 1 if symbol in ("NFLX", "TSLA") else rng.randint(4, 70)
        eps = round(rng.uniform(0.5, 6), 2)
        hist = []
        for q in range(4):
            est = round(eps * rng.uniform(0.85, 1.05), 2)
            act = round(est * (1 + rng.gauss(0.03, 0.06)), 2)
            period = (self._today() - timedelta(days=91 * (q + 1))).isoformat()
            hist.append({"period": period, "estimate": est, "actual": act, "surprise_pct": round((act / est - 1) * 100, 2)})
        return EarningsInfo((self._today() + timedelta(days=days)).isoformat(), rng.choice(["bmo", "amc"]), eps, hist)

    def ratings(self, symbol: str) -> Ratings | None:
        rng = self._rng("rec", symbol)
        return Ratings(self._today().replace(day=1).isoformat(), rng.randint(2, 15), rng.randint(5, 25), rng.randint(3, 15), rng.randint(0, 4), rng.randint(0, 2))

    def mood_inputs(self) -> MoodInputs:
        spy = self.market.minute_bars("SPY", 400)
        day_chg = (spy[-1].c / spy[0].o - 1) * 100 if len(spy) > 1 else 0.0
        rng = self._rng("mood", self._today())
        vix_prev = round(rng.uniform(14, 21), 2)
        now = self.market.now()
        events = []
        for i, (hhmm, name, impact) in enumerate(rng.sample(_SIM_EVENTS, 3)):
            h, m = map(int, hhmm.split(":"))
            et = datetime.combine(self._today() + timedelta(days=i // 2), datetime.min.time(), ET).replace(hour=h, minute=m)
            events.append(MacroEvent(et.astimezone(UTC).isoformat(), "US", name + " (simulated)", impact))
        return MoodInputs(
            vix=round(max(9, vix_prev - day_chg * 2.5 + rng.gauss(0, 0.4)), 2), vix_prev=vix_prev, fed_funds=4.33,
            ten_year=round(4.2 + rng.gauss(0, 0.05), 3), ten_year_prev=4.2, oil=round(70 + rng.gauss(0, 2), 2), oil_prev=70.0,
            events=sorted(events, key=lambda e: e.time), as_of=now.isoformat(), source="simulated",
        )

    def sources(self) -> list[dict]:
        sim = "simulated"
        return [
            _src("Market simulator", "Prices, minute bars, candles, news (demo)", sim, "ALPACA_API_KEY", "add Alpaca keys for live data"),
            _src("Paper-sim broker", "Fills, positions, account (demo)", sim, "ALPACA_API_KEY"),
            _src("SEC EDGAR", "Company filings", sim, "", "live automatically with Alpaca keys"),
            _src("Finnhub", "Second price source, earnings, analyst ratings, economic calendar", sim, "FINNHUB_API_KEY"),
            _src("FRED (St. Louis Fed)", "VIX, Fed funds, 10-year yield, oil", sim, "FRED_API_KEY"),
            _src("Financial Modeling Prep", "Company fundamentals", sim, "FMP_API_KEY", "demo uses built-in figures"),
            *_planned(),
        ]
