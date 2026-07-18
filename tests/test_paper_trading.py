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
        open=[100, 97, 99],
        high=[101, 100, 101],
        low=[99, 96, 98],
        close=[100, 99, 100],
        volume=[100, 100, 100],
        amount=[1000, 1000, 1000],
    )

    plan, events = _evaluate_entry(_plan(), series, TradingCostModel())

    assert plan["status"] == "open"
    assert plan["trigger_date"] == "2026-07-02"
    assert plan["entry_date"] == "2026-07-03"
    assert plan["entry_price"] > 99
    assert [event["event_type"] for event in events] == ["triggered", "opened"]


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

    plan, events = _evaluate_entry(_plan(), series, TradingCostModel())

    assert plan["status"] == "cancelled"
    assert events[-1]["payload"]["reason"] == "sealed_limit_up"


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
