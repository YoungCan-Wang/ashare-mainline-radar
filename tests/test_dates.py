from datetime import datetime, timezone

from ashare_mainline_radar.models import cn_market_date_from_ms


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def test_cn_market_date_uses_shanghai_trading_day() -> None:
    assert cn_market_date_from_ms(_ms("2026-07-12T16:00:00")) == "2026-07-13"


def test_cn_market_date_preserves_friday_boundary() -> None:
    assert cn_market_date_from_ms(_ms("2026-07-09T16:00:00")) == "2026-07-10"


def test_cn_market_date_allows_missing_timestamp() -> None:
    assert cn_market_date_from_ms(None) is None
