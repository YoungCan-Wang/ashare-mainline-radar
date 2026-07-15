from __future__ import annotations

from ashare_mainline_radar.market_structure import build_market_structure
from ashare_mainline_radar.models import KlineSeries


def _series(symbol: str, closes: list[float], amounts: list[float] | None = None) -> KlineSeries:
    return KlineSeries(
        symbol=symbol,
        timestamp=list(range(len(closes))),
        open=[value * 0.99 for value in closes],
        high=[value * 1.01 for value in closes],
        low=[value * 0.98 for value in closes],
        close=closes,
        volume=[1000.0] * len(closes),
        amount=amounts or [100.0] * len(closes),
    )


def _config() -> dict[str, object]:
    return {
        "market_context_groups": [
            {"name": "A股宽基环境", "symbols": ["000001.SH", "399001.SZ", "399006.SZ"]}
        ]
    }


def test_three_day_breakdown_is_confirmed() -> None:
    closes = [100 + i * 0.2 for i in range(37)] + [98, 97, 96]
    klines = {symbol: _series(symbol, closes) for symbol in ("000001.SH", "399001.SZ", "399006.SZ")}

    structure = build_market_structure(_config(), klines)

    assert structure.status == "破位确认"
    assert structure.confirmed_breakdown_ratio == 1


def test_single_break_reclaimed_is_watch_not_confirmed_breakdown() -> None:
    closes = [100 + i * 0.1 for i in range(38)] + [101, 105]
    klines = {symbol: _series(symbol, closes) for symbol in ("000001.SH", "399001.SZ", "399006.SZ")}

    structure = build_market_structure(_config(), klines)

    assert structure.status != "破位确认"
    assert structure.confirmed_breakdown_ratio == 0
