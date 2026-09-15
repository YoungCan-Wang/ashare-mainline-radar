from datetime import datetime, timedelta, timezone

from ashare_mainline_radar.models import KlineSeries, PriceLimitWatchReport
from ashare_mainline_radar.price_limit_watch import (
    _evidence_staleness_note,
    build_price_limit_watch,
)


def _timestamps(count: int) -> list[int]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [int((start + timedelta(days=index)).timestamp() * 1000) for index in range(count)]


def _series(symbol: str, bars: list[tuple[float, float, float, float]]) -> KlineSeries:
    return KlineSeries(
        symbol=symbol,
        timestamp=_timestamps(len(bars)),
        open=[bar[0] for bar in bars],
        high=[bar[1] for bar in bars],
        low=[bar[2] for bar in bars],
        close=[bar[3] for bar in bars],
        volume=[1000.0] * len(bars),
        amount=[bar[3] * 1000 for bar in bars],
    )


def test_daily_watch_separates_first_board_broken_board_and_broken_floor() -> None:
    base = [(10, 10.1, 9.9, 10)] * 20
    klines = {
        "000001.SZ": _series("000001.SZ", [*base, (10.2, 11, 10.1, 11)]),
        "000002.SZ": _series("000002.SZ", [*base, (10.2, 11, 9.8, 10.3)]),
        "000003.SZ": _series("000003.SZ", [*base, (9.5, 9.8, 9, 9.6)]),
    }
    instruments = {
        symbol: {"name": f"测试{index}", "type": "stock"}
        for index, symbol in enumerate(klines, start=1)
    }
    config = {
        "themes": [{"name": "测试主题", "symbols": ["000001.SZ"], "vehicles": []}]
    }

    report = build_price_limit_watch(config, klines, instruments)

    assert report.limit_up_touches == 2
    assert report.closed_limit_up == 1
    assert report.first_board_closed == 1
    assert report.broken_boards == 1
    assert report.limit_down_touches == 1
    assert report.broken_floors == 1
    assert {signal.signal_type for signal in report.signals} == {"首板封住", "炸板", "跌停打开"}
    first_board = next(signal for signal in report.signals if signal.signal_type == "首板封住")
    assert first_board.themes == ["测试主题"]
    assert first_board.verdict == "不买"
    assert report.ceiling_verdict == "关闭追板通道"
    assert report.floor_verdict == "关闭抄底通道"
    assert report.backtest_cases[0].test_trades == 12495


def test_daily_watch_excludes_first_five_listed_bars() -> None:
    bars = [(10, 10.1, 9.9, 10)] * 4 + [(10.2, 11, 10.1, 11)]
    series = _series("000001.SZ", bars)
    listing_date = datetime.fromtimestamp(series.timestamp[0] / 1000, timezone.utc).date().isoformat()

    report = build_price_limit_watch(
        {"themes": []},
        {"000001.SZ": series},
        {"000001.SZ": {"name": "新股", "ext": {"listing_date": listing_date}}},
    )

    assert report.limit_up_touches == 0


def test_daily_watch_does_not_treat_short_history_as_new_listing() -> None:
    series = _series("000001.SZ", [(10, 10.1, 9.9, 10), (10.2, 11, 10.1, 11)])

    report = build_price_limit_watch(
        {"themes": []},
        {"000001.SZ": series},
        {"000001.SZ": {"name": "老股票", "ext": {"listing_date": "2000-01-01"}}},
    )

    assert report.limit_up_touches == 1
    assert report.first_board_closed == 1


def test_daily_watch_marks_one_price_limits_as_untradeable() -> None:
    base = [(10, 10.1, 9.9, 10)] * 20
    report = build_price_limit_watch(
        {"themes": []},
        {
            "000001.SZ": _series("000001.SZ", [*base, (11, 11, 11, 11)]),
            "000002.SZ": _series("000002.SZ", [*base, (9, 9, 9, 9)]),
        },
        {
            "000001.SZ": {"name": "一字涨停股"},
            "000002.SZ": {"name": "一字跌停股"},
        },
    )

    assert report.one_price_limit_up == 1
    assert report.one_price_limit_down == 1
    assert {signal.signal_type for signal in report.signals} == {"一字涨停", "一字跌停"}


def test_daily_watch_lists_floor_to_ceiling_only_once() -> None:
    base = [(10, 10.1, 9.9, 10)] * 20
    report = build_price_limit_watch(
        {"themes": []},
        {"000001.SZ": _series("000001.SZ", [*base, (9, 11, 9, 11)])},
        {"000001.SZ": {"name": "反转样本"}},
    )

    assert report.floor_to_ceiling == 1
    assert report.limit_up_touches == 1
    assert report.limit_down_touches == 1
    assert [signal.signal_type for signal in report.signals] == ["地天板"]


def _timestamps_from(start: datetime, count: int) -> list[int]:
    return [int((start + timedelta(days=index)).timestamp() * 1000) for index in range(count)]


def _series_from(symbol: str, start: datetime, bars: list[tuple[float, float, float, float]]) -> KlineSeries:
    return KlineSeries(
        symbol=symbol,
        timestamp=_timestamps_from(start, len(bars)),
        open=[bar[0] for bar in bars],
        high=[bar[1] for bar in bars],
        low=[bar[2] for bar in bars],
        close=[bar[3] for bar in bars],
        volume=[1000.0] * len(bars),
        amount=[bar[3] * 1000 for bar in bars],
    )


def _flat_report_ending(end: datetime) -> PriceLimitWatchReport:
    bars = [(10, 10.1, 9.9, 10)] * 21
    klines = {"000001.SZ": _series_from("000001.SZ", end - timedelta(days=20), bars)}
    return build_price_limit_watch({"themes": []}, klines, {"000001.SZ": {"name": "测试"}})


def test_evidence_staleness_note_flags_expired_evidence() -> None:
    note = _evidence_staleness_note("2026-08-12", "2026-09-14")
    assert note is not None
    assert "2026-08-12" in note
    assert "33" in note


def test_evidence_staleness_note_accepts_fresh_evidence() -> None:
    assert _evidence_staleness_note("2026-08-12", "2026-09-10") is None
    assert _evidence_staleness_note("2026-08-12", "2026-09-11") is None


def test_evidence_staleness_note_ignores_missing_or_bad_dates() -> None:
    assert _evidence_staleness_note("2026-08-12", None) is None
    assert _evidence_staleness_note("2026-08-12", "not-a-date") is None


def test_report_flags_stale_evidence_in_notes() -> None:
    report = _flat_report_ending(datetime(2026, 9, 14, tzinfo=timezone.utc))
    assert report.as_of == "2026-09-14"
    assert report.notes[0].startswith("可执行证据已过期")


def test_report_omits_staleness_note_when_evidence_fresh() -> None:
    report = _flat_report_ending(datetime(2026, 8, 20, tzinfo=timezone.utc))
    assert report.as_of == "2026-08-20"
    assert not any("过期" in note for note in report.notes)
