from datetime import datetime, timezone

from ashare_mainline_radar.engine import _clip_klines_as_of, _filter_intel_as_of, _parse_as_of
from ashare_mainline_radar.models import IntelItem, KlineSeries, cn_market_date_from_ms


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def test_cn_market_date_uses_shanghai_trading_day() -> None:
    assert cn_market_date_from_ms(_ms("2026-07-12T16:00:00")) == "2026-07-13"


def test_cn_market_date_preserves_friday_boundary() -> None:
    assert cn_market_date_from_ms(_ms("2026-07-09T16:00:00")) == "2026-07-10"


def test_cn_market_date_allows_missing_timestamp() -> None:
    assert cn_market_date_from_ms(None) is None


def _series(dates: list[str]) -> KlineSeries:
    timestamps = [_ms(f"{value}T08:00:00") for value in dates]
    values = [float(index) for index in range(len(dates))]
    return KlineSeries("TEST.SZ", timestamps, values, values, values, values, values, values)


def test_point_in_time_kline_clip_excludes_future_days() -> None:
    clipped = _clip_klines_as_of(
        _series(["2026-06-26", "2026-06-29", "2026-06-30"]),
        _parse_as_of("2026-06-29"),
    )

    assert len(clipped.close) == 2
    assert cn_market_date_from_ms(clipped.last_timestamp) == "2026-06-29"


def test_monthly_clip_excludes_unfinished_cutoff_month() -> None:
    clipped = _clip_klines_as_of(
        _series(["2026-05-01", "2026-06-01", "2026-07-01"]),
        _parse_as_of("2026-06-29"),
        completed_months_only=True,
    )

    assert len(clipped.close) == 1


def test_point_in_time_intelligence_excludes_future_and_unknown_dates() -> None:
    items = [
        IntelItem("test", "known", published_at="2026-06-29"),
        IntelItem("test", "future", published_at="2026-06-30"),
        IntelItem("test", "unknown"),
    ]

    filtered = _filter_intel_as_of(items, _parse_as_of("2026-06-29"))

    assert [item.title for item in filtered] == ["known"]
