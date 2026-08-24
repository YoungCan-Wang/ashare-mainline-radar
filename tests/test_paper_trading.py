from __future__ import annotations

from datetime import datetime, timezone

from ashare_mainline_radar.execution import TradingCostModel
from ashare_mainline_radar.models import KlineSeries
from ashare_mainline_radar.paper_trading import _evaluate_entry, _evaluate_exit


def _timestamps(*dates: str) -> list[int]:
    return [int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000) for value in dates]


def _plan(**overrides):
    plan = {
        "plan_key": "2026-07-01:600001.SH",
        "source_run_key": "run",
        "symbol": "600001.SH",
        "name": "测试股份",
        "theme": "测试主线",
        "signal_date": "2026-07-01",
        "signal_price": 100,
        "status": "watching",
        "entry_mode": "pullback_close_reclaim",
        "entry_zone_low": 95.5,
        "entry_zone_high": 98.5,
        "confirm_price": 101.2,
        "stop_price": 92,
        "valid_for_days": 5,
        "max_hold_days": 15,
        "max_position_fraction": 0.25,
        "initial_position_fraction": 1 / 12,
        "inactive_theme_days": 0,
        "exit_delay_days": 0,
        "cost_payload": {},
    }
    plan.update(overrides)
    return plan


def test_paper_plan_opens_only_after_close_confirmation() -> None:
    series = KlineSeries(
        symbol="600001.SH",
        timestamp=_timestamps("2026-07-01", "2026-07-02", "2026-07-03"),
        open=[100, 97, 98.0],
        high=[101, 100, 101],
        low=[99, 96, 97],
        close=[100, 99, 100],
        volume=[100, 100, 100],
        amount=[1000, 1000, 1000],
    )

    plan, events = _evaluate_entry(_plan(), series, TradingCostModel())

    assert plan["status"] == "open"
    assert plan["trigger_date"] == "2026-07-02"
    assert plan["entry_date"] == "2026-07-03"
    assert plan["entry_price"] > 98.0
    assert [event["event_type"] for event in events] == ["triggered", "opened"]
    opened = events[-1]
    assert opened["payload"]["raw_price"] == 98.0
    assert opened["payload"]["price_basis"] == "overnight_limit_open"
    assert opened["payload"]["suggested_buy_price"] == 98.5
    assert "隔夜限价挂单" in opened["payload"]["price_note"]
    triggered = events[0]
    assert triggered["payload"]["working_order_type"] == "overnight_limit"
    assert triggered["payload"]["suggested_buy_price"] == 98.5
    assert plan["cost_payload"]["working_order"]["suggested_buy_price"] == 98.5


def test_paper_plan_cancels_when_next_open_is_sealed_limit_up() -> None:
    series = KlineSeries(
        symbol="600001.SH",
        timestamp=_timestamps("2026-07-01", "2026-07-02", "2026-07-03"),
        open=[100, 97, 108.9],
        high=[101, 100, 108.9],
        low=[99, 96, 108.9],
        close=[100, 99, 108.9],
        volume=[100, 100, 100],
        amount=[1000, 1000, 1000],
    )

    plan, events = _evaluate_entry(
        _plan(entry_mode="breakout_close_confirm", confirm_price=99),
        series,
        TradingCostModel(),
    )

    assert plan["status"] == "cancelled"
    assert events[-1]["payload"]["reason"] == "sealed_limit_up"
    assert events[-1]["payload"]["price_basis"] == "sealed_limit_up"


def _denghai_plan(**overrides):
    fields = {
        "plan_key": "2026-08-18:002041.SZ",
        "symbol": "002041.SZ",
        "name": "登海种业",
        "signal_date": "2026-08-18",
        "entry_mode": "pullback_close_reclaim",
        "entry_zone_low": 9.36,
        "entry_zone_high": 9.65,
        "confirm_price": 9.92,
        "stop_price": 8.61,
    }
    fields.update(overrides)
    return _plan(**fields)


def _denghai_series(*, extra_dates: list[str] | None = None, extra_bars: list[tuple[float, float, float, float]] | None = None) -> KlineSeries:
    dates = ["2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"]
    opens = [9.50, 9.80, 9.50, 9.71]
    highs = [9.70, 9.90, 10.05, 9.85]
    lows = [9.40, 9.70, 9.40, 9.70]
    closes = [9.60, 9.85, 9.92, 9.78]
    if extra_dates:
        dates.extend(extra_dates)
        for open_, high, low, close in extra_bars or []:
            opens.append(open_)
            highs.append(high)
            lows.append(low)
            closes.append(close)
    n = len(dates)
    return KlineSeries(
        symbol="002041.SZ",
        timestamp=_timestamps(*dates),
        open=opens,
        high=highs,
        low=lows,
        close=closes,
        volume=[100] * n,
        amount=[1000] * n,
    )


def test_pullback_gap_above_zone_does_not_buy_next_open() -> None:
    plan, events = _evaluate_entry(_denghai_plan(), _denghai_series(), TradingCostModel())

    assert plan["status"] == "triggered"
    assert plan["trigger_date"] == "2026-08-20"
    assert "entry_date" not in plan
    assert [event["event_type"] for event in events] == ["triggered"]
    assert events[0]["payload"]["suggested_buy_price"] == 9.65
    assert events[0]["payload"]["working_order_type"] == "overnight_limit"
    assert "隔夜限价挂单" in events[0]["payload"]["working_order_note"]
    assert plan["cost_payload"]["working_order"]["suggested_buy_price"] == 9.65


def test_pullback_later_dip_fills_at_zone_high() -> None:
    series = _denghai_series(extra_dates=["2026-08-22"], extra_bars=[(9.80, 9.85, 9.60, 9.70)])

    plan, events = _evaluate_entry(_denghai_plan(), series, TradingCostModel())

    assert plan["status"] == "open"
    assert plan["entry_date"] == "2026-08-22"
    assert plan["raw_entry_price"] == 9.65
    opened = events[-1]
    assert opened["event_type"] == "opened"
    assert opened["payload"]["raw_price"] == 9.65
    assert opened["payload"]["price_basis"] == "overnight_limit"
    assert opened["payload"]["reason"] == "overnight_limit"
    assert opened["payload"]["suggested_buy_price"] == 9.65
    assert opened["payload"]["price_note"] == "隔夜限价挂单，开盘高于建议购买价，按建议购买价限价成交"


def test_pullback_window_without_zone_touch_expires() -> None:
    series = _denghai_series(
        extra_dates=["2026-08-24", "2026-08-25"],
        extra_bars=[(9.80, 9.90, 9.72, 9.82), (9.85, 9.95, 9.74, 9.88)],
    )

    plan, events = _evaluate_entry(_denghai_plan(), series, TradingCostModel())

    assert plan["status"] == "expired"
    assert plan["exit_reason"] == "确认后有效期内隔夜限价未成交"
    expired = events[-1]
    assert expired["event_type"] == "expired"
    assert expired["payload"]["reason"] == "overnight_limit_not_tagged"
    assert expired["payload"]["price_basis"] == "overnight_limit_not_tagged"
    assert expired["payload"]["suggested_buy_price"] == 9.65
    assert "opened" not in [event["event_type"] for event in events]


def test_close_run_surfaces_next_day_working_order_without_fill() -> None:
    dates = ["2026-08-18", "2026-08-19", "2026-08-20"]
    series = KlineSeries(
        symbol="002041.SZ",
        timestamp=_timestamps(*dates),
        open=[9.50, 9.80, 9.50],
        high=[9.70, 9.90, 10.05],
        low=[9.40, 9.70, 9.40],
        close=[9.60, 9.85, 9.92],
        volume=[100, 100, 100],
        amount=[1000, 1000, 1000],
    )

    pullback, pullback_events = _evaluate_entry(_denghai_plan(), series, TradingCostModel())
    assert pullback["status"] == "triggered"
    assert pullback["cost_payload"]["working_order"]["suggested_buy_price"] == 9.65
    assert "隔夜限价挂单" in pullback_events[-1]["payload"]["working_order_note"]

    breakout, breakout_events = _evaluate_entry(
        _denghai_plan(entry_mode="breakout_close_confirm"),
        series,
        TradingCostModel(),
    )
    assert breakout["status"] == "triggered"
    assert "suggested_buy_price" not in breakout["cost_payload"]["working_order"]
    assert breakout_events[-1]["payload"]["working_order_type"] == "market_on_open"
    assert "开盘价" in breakout_events[-1]["payload"]["working_order_note"]


def test_breakout_still_opens_next_day_at_open_above_zone() -> None:
    series = _denghai_series()

    plan, events = _evaluate_entry(
        _denghai_plan(entry_mode="breakout_close_confirm"),
        series,
        TradingCostModel(),
    )

    assert plan["status"] == "open"
    assert plan["entry_date"] == "2026-08-21"
    assert plan["raw_entry_price"] == 9.71
    opened = events[-1]
    assert opened["payload"]["price_basis"] == "next_session_open"
    assert opened["payload"]["raw_price"] == 9.71
    assert opened["payload"]["working_order_type"] == "market_on_open"
    assert "suggested_buy_price" not in opened["payload"]
    assert "开盘价" in events[0]["payload"]["working_order_note"]


def test_paper_exit_waits_through_sealed_limit_down() -> None:
    series = KlineSeries(
        symbol="600001.SH",
        timestamp=_timestamps("2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"),
        open=[10, 9.5, 8.1, 8.2],
        high=[10.2, 9.6, 8.1, 8.5],
        low=[9.9, 8.9, 8.1, 8.0],
        close=[10, 9.0, 8.1, 8.4],
        volume=[100, 100, 100, 100],
        amount=[1000, 1000, 1000, 1000],
    )
    plan = _plan(
        status="open",
        signal_price=10,
        stop_price=9.2,
        entry_date="2026-07-01",
        raw_entry_price=10,
        entry_price=10.005,
    )

    plan, events = _evaluate_exit(plan, series, TradingCostModel())

    assert plan["status"] == "closed"
    assert plan["exit_date"] == "2026-07-04"
    assert plan["exit_delay_days"] == 1
    assert [event["event_type"] for event in events] == ["exit_delayed", "closed"]


def test_open_paper_plan_marks_net_return_after_all_costs() -> None:
    series = KlineSeries(
        symbol="600001.SH",
        timestamp=_timestamps("2026-07-01", "2026-07-02"),
        open=[10, 10.5],
        high=[10.2, 11.2],
        low=[9.9, 10.4],
        close=[10, 11],
        volume=[100, 100],
        amount=[1000, 1100],
    )
    plan = _plan(
        status="open",
        stop_price=9.2,
        entry_date="2026-07-01",
        raw_entry_price=10,
        entry_price=10.005,
    )

    plan, events = _evaluate_exit(plan, series, TradingCostModel())

    assert events == []
    assert plan["status"] == "open"
    assert plan["mark_date"] == "2026-07-02"
    assert plan["mark_price"] < 11
    assert 0 < plan["net_return"] < 0.1


def test_exit_delay_is_not_counted_twice_on_same_market_date() -> None:
    series = KlineSeries(
        symbol="600001.SH",
        timestamp=_timestamps("2026-07-01", "2026-07-02", "2026-07-03"),
        open=[10, 9.5, 8.1],
        high=[10.2, 9.6, 8.1],
        low=[9.9, 8.9, 8.1],
        close=[10, 9.0, 8.1],
        volume=[100, 100, 100],
        amount=[1000, 1000, 1000],
    )
    plan = _plan(
        status="open",
        signal_price=10,
        stop_price=9.2,
        entry_date="2026-07-01",
        raw_entry_price=10,
        entry_price=10.005,
    )

    plan, _ = _evaluate_exit(plan, series, TradingCostModel())
    plan, _ = _evaluate_exit(plan, series, TradingCostModel())

    assert plan["status"] == "open"
    assert plan["exit_delay_days"] == 1


def test_shadow_plan_records_three_day_theme_exit_reason() -> None:
    series = KlineSeries(
        symbol="600001.SH",
        timestamp=_timestamps("2026-07-01", "2026-07-02"),
        open=[10, 10.2],
        high=[10.2, 10.4],
        low=[9.9, 10.1],
        close=[10, 10.3],
        volume=[100, 100],
        amount=[1000, 1000],
    )
    plan = _plan(
        status="open",
        strategy_version="mainline-v2-theme-exit-3d-frozen-20260718",
        theme_exit_days=3,
        exit_signal_date="2026-07-01",
        entry_date="2026-07-01",
        raw_entry_price=10,
        entry_price=10.005,
    )

    plan, events = _evaluate_exit(plan, series, TradingCostModel())

    assert plan["status"] == "closed"
    assert plan["exit_reason"] == "主线连续3日退出前三"
    assert events[-1]["strategy_version"] == "mainline-v2-theme-exit-3d-frozen-20260718"
    assert events[-1]["payload"]["price_basis"] == "next_session_open"
    assert events[-1]["payload"]["reason"] == "主线连续3日退出前三"
