from datetime import UTC, datetime, timedelta

from rahbeh.market.base import Bar, Fundamentals, NewsItem, Quote
from rahbeh.pipeline import checks, features, halal, laya

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)


def bars(n=60, start=100.0, step=0.05, vol=1000.0):
    return [Bar(NOW - timedelta(minutes=n - i), start + i * step, start + i * step + 0.1, start + i * step - 0.1,
                start + (i + 1) * step, vol) for i in range(n)]


def test_data_check_passes_clean_data():
    b = bars()
    q = Quote("X", b[-1].c, NOW, "a")
    assert checks.check_data(b, q, Quote("X", q.price * 1.001, NOW, "b"), NOW).ok


def test_data_check_catches_problems():
    b = bars()
    q = Quote("X", b[-1].c, NOW, "a")
    assert not checks.check_data(b, q, Quote("X", q.price * 1.02, NOW, "b"), NOW).ok  # sources disagree
    assert not checks.check_data(b, Quote("X", q.price, NOW - timedelta(minutes=20), "a"), None, NOW).ok  # stale
    spike = bars()
    spike[-3] = Bar(spike[-3].ts, 100, 200, 99, 150, 1000)
    assert not checks.check_data(spike, q, None, NOW).ok  # impossible jump
    zero = bars(vol=0)
    assert not checks.check_data(zero, q, None, NOW).ok
    assert "single price source" in checks.check_data(b, q, None, NOW).warnings[0]


def test_features_uptrend():
    f = features.compute(bars(), [])
    assert f.trend == "up" and f.change_30m_pct > 0 and f.rsi14 > 70 and f.momentum_score > 0


def test_laya_dedupes_and_scores_news():
    f = features.compute(bars(), [])
    news = [NewsItem(str(i), "Acme beats estimates and raises guidance", "wire", NOW - timedelta(minutes=5), ["ACME"]) for i in range(5)]
    assert len(laya.dedupe(news)) == 1
    r = laya.evaluate("ACME", f, news, NOW)
    assert r.sentiment > 0 and r.company_news
    bad = [NewsItem("1", "Acme misses revenue estimates and cuts outlook", "wire", NOW, ["ACME"])]
    assert not laya.evaluate("ACME", f, bad, NOW).worth_a_look


def test_halal_screen():
    clean = Fundamentals("A", "A", "Technology", "Software", 100e9, 10e9, 2e9, 5e9, 5e9)
    assert halal.screen(clean).passes
    bank = Fundamentals("B", "B", "Financials", "Banks", 100e9, 10e9, 2e9, 5e9, 5e9, business_tags=["conventional_finance"])
    assert not halal.screen(bank).passes
    levered = Fundamentals("C", "C", "Utilities", "Power", 100e9, 10e9, 2e9, 40e9, 5e9)
    assert any("debt" in r for r in halal.screen(levered).reasons)
    assert not halal.screen(None).passes


def test_aggregate_candles():
    from rahbeh.market.base import aggregate

    start = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)
    minute = [Bar(start + timedelta(minutes=i), 100 + i, 101 + i, 99 + i, 100.5 + i, 10) for i in range(12)]
    five = aggregate(minute, 5)
    assert len(five) == 3
    assert five[0].o == 100 and five[0].c == 104.5 and five[0].h == 105 and five[0].l == 99 and five[0].v == 50
    assert five[-1].v == 20  # partial last candle
