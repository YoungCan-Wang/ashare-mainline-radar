from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ashare_mainline_radar.limit_up_backtest import (
    build_limit_up_backtest_report,
    collect_limit_down_events,
    collect_limit_up_events,
)
from ashare_mainline_radar.models import KlineSeries


def _timestamps(count: int) -> list[int]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [int((start + timedelta(days=index)).timestamp() * 1000) for index in range(count)]


def _series(symbol: str, bars: list[tuple[float, float, float, float, float]]) -> KlineSeries:
    return KlineSeries(
        symbol=symbol,
        timestamp=_timestamps(len(bars)),
        open=[bar[0] for bar in bars],
        high=[bar[1] for bar in bars],
        low=[bar[2] for bar in bars],
        close=[bar[3] for bar in bars],
        volume=[bar[4] for bar in bars],
        amount=[bar[3] * bar[4] for bar in bars],
    )


def test_reseal_event_and_limit_down_exit_delay_are_recorded() -> None:
    bars = [(10, 10.1, 9.9, 10, 1000)] * 85
    bars.extend(
        [
            (10.2, 11, 10.2, 11, 2000),
            (9.9, 9.9, 9.9, 9.9, 1500),
            (9.8, 10.0, 9.7, 9.9, 1600),
            (10.0, 10.2, 9.9, 10.1, 1700),
            (10.1, 10.3, 10.0, 10.2, 1800),
            (10.2, 10.4, 10.1, 10.3, 1900),
        ]
    )
    config = {"themes": [], "market_context_groups": []}
    instruments = {"000001.SZ": {"name": "测试股份", "type": "stock", "ext": {}}}

    events, _ = collect_limit_up_events(
        config,
        {"000001.SZ": _series("000001.SZ", bars)},
        instruments,
        warmup_days=80,
    )

    assert len(events) == 1
    event = events[0]
    assert event.closed_limit_up is True
    assert event.one_price_limit_up is False
    assert event.next_day_limit_down is True
    assert event.exit_delay_days["next_open"] == 1
    assert event.returns["next_open"] is not None


def test_ceiling_to_floor_and_floor_to_ceiling_paths_are_separated() -> None:
    base = [(10, 10.1, 9.9, 10, 1000)] * 85
    ceiling_floor = [*base, (10.5, 11, 9, 9, 3000), *[(9, 9.2, 8.9, 9.1, 1000)] * 5]
    floor_ceiling = [*base, (9.5, 11, 9, 11, 3000), *[(11, 11.2, 10.9, 11.1, 1000)] * 5]
    instruments = {
        "000001.SZ": {"name": "甲股份", "type": "stock", "ext": {}},
        "000002.SZ": {"name": "乙股份", "type": "stock", "ext": {}},
    }
    events, metadata = collect_limit_up_events(
        {"themes": [], "market_context_groups": []},
        {
            "000001.SZ": _series("000001.SZ", ceiling_floor),
            "000002.SZ": _series("000002.SZ", floor_ceiling),
        },
        instruments,
        warmup_days=80,
    )
    report = build_limit_up_backtest_report(events, metadata)

    assert report["path_risks"]["ceiling_to_floor"]["signals"] == 1
    assert report["path_risks"]["floor_to_ceiling"]["signals"] == 1


def test_one_price_limit_up_is_excluded_from_executable_variant() -> None:
    bars = [(10, 10.1, 9.9, 10, 1000)] * 85
    bars.extend([(11, 11, 11, 11, 1000), *[(11, 11.2, 10.9, 11.1, 1000)] * 5])
    events, metadata = collect_limit_up_events(
        {"themes": [], "market_context_groups": []},
        {"000001.SZ": _series("000001.SZ", bars)},
        {"000001.SZ": {"name": "测试股份", "type": "stock", "ext": {}}},
        warmup_days=80,
    )
    report = build_limit_up_backtest_report(events, metadata)

    assert report["variants"]["touch_fill_naive_baseline"]["all"]["signals"] == 1
    assert report["variants"]["close_sealed_non_one_price_conditional"]["all"]["signals"] == 0


def test_independent_limit_down_event_studies_sealed_and_broken_floors() -> None:
    base = [(10, 10.1, 9.9, 10, 1000)] * 85
    sealed = [*base, (9.5, 9.8, 9, 9, 3000), *[(9, 9.2, 8.9, 9.1, 1000)] * 5]
    broken = [*base, (9.5, 9.8, 9, 9.6, 3000), *[(9.6, 9.8, 9.5, 9.7, 1000)] * 5]
    instruments = {
        "000001.SZ": {"name": "甲股份", "type": "stock", "ext": {}},
        "000002.SZ": {"name": "乙股份", "type": "stock", "ext": {}},
    }

    events, metadata = collect_limit_down_events(
        {"themes": [], "market_context_groups": []},
        {
            "000001.SZ": _series("000001.SZ", sealed),
            "000002.SZ": _series("000002.SZ", broken),
        },
        instruments,
        warmup_days=80,
    )
    report = build_limit_up_backtest_report([], metadata, events)

    assert len(events) == 2
    assert report["floor_variants"]["close_limit_down_buy_conditional"]["all"]["signals"] == 1
    assert report["floor_variants"]["broken_floor_rebound_conditional"]["all"]["signals"] == 1
