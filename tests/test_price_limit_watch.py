from datetime import datetime, timedelta, timezone

from ashare_mainline_radar.models import KlineSeries
from ashare_mainline_radar.price_limit_watch import build_price_limit_watch


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
