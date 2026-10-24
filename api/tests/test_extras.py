"""Parsers for the live providers, fed payloads in each provider's documented shape, plus mood rules."""

from datetime import UTC, date, datetime, timedelta

from rahbeh.market.extras import (
    MacroEvent,
    MoodInputs,
    parse_finnhub_earnings,
    parse_finnhub_economic,
    parse_finnhub_recommendation,
    parse_fmp_economic,
    parse_fred,
    parse_sec_submissions,
)
from rahbeh.pipeline import mood


def test_sec_submissions():
    data = {"filings": {"recent": {
        "form": ["4", "8-K", "S-8", "10-Q"],
        "filingDate": ["2026-10-20", "2026-10-15", "2026-10-01", "2026-08-01"],
        "accessionNumber": ["0000320193-26-000101", "0000320193-26-000100", "0000320193-26-000090", "0000320193-26-000080"],
        "primaryDocument": ["xslF345X05/wk-form4.xml", "aapl-8k.htm", "s8.htm", "aapl-10q.htm"],
        "primaryDocDescription": ["", "8-K", "", "10-Q"],
    }}}
    out = parse_sec_submissions(data, 320193, 10)
    assert [f.form for f in out] == ["4", "8-K", "10-Q"]  # S-8 is not a form we track
    assert out[1].url == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000100/aapl-8k.htm"
    assert out[0].description == "Insider trade"


def test_finnhub_earnings_and_recommendation():
    cal = {"earningsCalendar": [
        {"date": "2026-10-30", "epsEstimate": 1.6, "hour": "amc", "symbol": "AAPL"},
        {"date": "2026-10-01", "epsEstimate": 1.5, "hour": "amc", "symbol": "AAPL"},
    ]}
    sur = [{"actual": 1.64, "estimate": 1.6, "period": "2026-06-30", "surprisePercent": 2.5},
           {"actual": 1.4, "estimate": 1.5, "period": "2026-03-31", "surprisePercent": -6.67}]
    e = parse_finnhub_earnings(cal, sur, date(2026, 10, 24))
    assert e.next_date == "2026-10-30" and e.next_hour == "amc" and e.days_until(date(2026, 10, 24)) == 6
    assert e.history[0]["period"] == "2026-06-30"
    r = parse_finnhub_recommendation([{"period": "2026-09-01", "strongBuy": 1, "buy": 1, "hold": 1, "sell": 0, "strongSell": 0},
                                      {"period": "2026-10-01", "strongBuy": 10, "buy": 20, "hold": 5, "sell": 1, "strongSell": 0}])
    assert r.period == "2026-10-01" and r.total == 36 and 3.9 < r.score < 4.2


def test_fred_and_calendars():
    assert parse_fred({"observations": [{"date": "2026-10-23", "value": "."}, {"date": "2026-10-22", "value": "18.5"},
                                        {"date": "2026-10-21", "value": "17.0"}]}) == (18.5, 17.0)
    fh = parse_finnhub_economic({"economicCalendar": [{"time": "2026-10-24 12:30:00", "country": "US", "event": "CPI MoM", "impact": "high", "prev": 0.2, "estimate": 0.3}]})
    assert fh[0].impact == "high" and fh[0].time.startswith("2026-10-24T12:30")
    fmp = parse_fmp_economic([{"date": "2026-10-24 18:00:00", "country": "US", "event": "Fed Interest Rate Decision", "impact": "High"}])
    assert fmp[0].impact == "high"


def test_mood_levels():
    now = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)
    calm = mood.assess(MoodInputs(vix=15, vix_prev=15), 0.3, 60, now)
    assert calm.level == "calm" and calm.risk_multiplier == 1
    careful = mood.assess(MoodInputs(vix=24, vix_prev=23), 0.0, 60, now)
    assert careful.level == "careful" and careful.risk_multiplier == 0.5
    assert mood.assess(MoodInputs(vix=15), -2.5, 10, now).level == "stormy"
    event = MacroEvent((now + timedelta(minutes=20)).isoformat(), "US", "FOMC rate decision", "high")
    m = mood.assess(MoodInputs(vix=15, events=[event]), 0.1, 60, now)
    assert m.level == "careful" and m.next_event["event"] == "FOMC rate decision"
