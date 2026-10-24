from datetime import UTC, datetime

from rahbeh.broker.base import Account, Position
from rahbeh.pipeline import risk

LIMITS = risk.Limits(risk_per_trade_pct=1.0, daily_loss_limit_pct=2.0, max_position_pct=20, max_sector_pct=40,
                     max_open_positions=4, max_trades_per_day=6, min_reward_risk=1.5)
# 11:00 ET on a weekday
NOW = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)


def ctx(**kw):
    base = dict(account=Account(100_000, 100_000, 100_000, 100_000), positions=[], sector_of={},
                realized_pnl_today=0, trades_today=0, kill_switch=False, now=NOW, session_rules=True)
    base.update(kw)
    return risk.RiskContext(**base)


def req(entry=100.0, stop=98.0, target=104.0, symbol="AAPL", sector="Technology"):
    return risk.TradeRequest(symbol, sector, entry, stop, target)


def test_sizes_to_one_percent_risk():
    d = risk.evaluate(req(), ctx(), LIMITS)
    assert d.approved
    # 1% of 100k = 1000 risk / $2 per share = 500 shares, capped by 20% position = 200 shares
    assert d.qty == 200
    assert d.risk_amount == 400


def test_risk_never_exceeds_hard_cap_even_if_settings_say_more():
    loose = risk.Limits(**{**LIMITS.__dict__, "risk_per_trade_pct": 10, "max_position_pct": 100})
    d = risk.evaluate(req(), ctx(), loose)
    assert d.risk_amount <= 100_000 * risk.HARD_MAX_RISK_PER_TRADE_PCT / 100


def test_kill_switch_blocks():
    d = risk.evaluate(req(), ctx(kill_switch=True), LIMITS)
    assert not d.approved and d.qty == 0
    assert any(c.name == "kill_switch" for c in d.failed)


def test_daily_loss_stop():
    d = risk.evaluate(req(), ctx(account=Account(97_500, 97_500, 97_500, 100_000)), LIMITS)
    assert not d.approved
    assert any(c.name == "daily_loss" for c in d.failed)


def test_bad_order_shape_and_reward_risk():
    assert not risk.evaluate(req(stop=101), ctx(), LIMITS).approved  # stop above entry
    d = risk.evaluate(req(target=101), ctx(), LIMITS)  # 0.5R
    assert any(c.name == "reward_risk" for c in d.failed)


def test_stop_too_wide():
    d = risk.evaluate(req(stop=80, target=150), ctx(), LIMITS)
    assert any(c.name == "stop_distance" for c in d.failed)


def test_sector_exposure_caps_size():
    held = [Position("MSFT", 90, 400, 400)]  # $36k tech already = 36%
    d = risk.evaluate(req(), ctx(positions=held, sector_of={"MSFT": "Technology"}), LIMITS)
    assert d.approved
    assert d.qty == 40  # only $4k of room left under the 40% sector cap


def test_already_held_and_max_positions():
    held = [Position(s, 1, 10, 10) for s in ["AAPL", "B", "C", "D"]]
    d = risk.evaluate(req(), ctx(positions=held), LIMITS)
    names = {c.name for c in d.failed}
    assert {"not_held", "open_positions"} <= names


def test_session_window():
    early = datetime(2026, 10, 21, 13, 31, tzinfo=UTC)  # 09:31 ET
    assert not risk.evaluate(req(), ctx(now=early), LIMITS).approved
    late = datetime(2026, 10, 21, 19, 40, tzinfo=UTC)  # 15:40 ET
    assert not risk.evaluate(req(), ctx(now=late), LIMITS).approved
    assert risk.should_flatten(datetime(2026, 10, 21, 19, 50, tzinfo=UTC), True)
    assert not risk.should_flatten(datetime(2026, 10, 21, 19, 49, tzinfo=UTC), True)


def test_allowed_list():
    lim = risk.Limits(**{**LIMITS.__dict__, "allowed_symbols": ["msft"]})
    assert not risk.evaluate(req(), ctx(), lim).approved


def test_trailing_stop():
    assert risk.trail_stop(100, 98, 98, 101) == 98  # +0.5R: no change
    assert risk.trail_stop(100, 98, 98, 102) == 100  # +1R: breakeven
    assert risk.trail_stop(100, 98, 100, 105) == 103  # +2.5R: trail 1R behind
    assert risk.trail_stop(100, 98, 103, 104) == 103  # never lowers
