from ashare_mainline_radar.models import KlineSeries, TradingGate
from ashare_mainline_radar.monthly_base import detect_monthly_base


def _gate(level: str = "green") -> TradingGate:
    return TradingGate(
        level=level,
        state="允许寻找买点",
        score=70,
        max_initial_position_fraction=1 / 3,
    )


def _series(closes: list[float], highs: list[float], lows: list[float], amounts: list[float]) -> KlineSeries:
    return KlineSeries(
        symbol="000001.SZ",
        timestamp=list(range(len(closes))),
        open=closes,
        high=highs,
        low=lows,
        close=closes,
        volume=amounts,
        amount=amounts,
    )


def test_detects_long_monthly_base_near_upper_boundary() -> None:
    closes = [24, 26, 23, 27, 25, 29, 24, 28, 26, 30, 25, 29, 27, 31, 26, 29, 28, 30, 31]
    highs = [value + 3 for value in closes]
    lows = [value - 3 for value in closes]
    amounts = [120, 118, 116, 112, 110, 108, 104, 102, 100, 98, 96, 94, 92, 90, 88, 86, 84, 82, 90]

    candidate = detect_monthly_base("000001.SZ", "测试公司", ["测试主题"], _series(closes, highs, lows, amounts), _gate())

    assert candidate is not None
    assert candidate.box_months == 18
    assert candidate.stage == "箱顶蓄势"
    assert candidate.box_low < candidate.last_close < candidate.box_high
    assert "等待放量突破" in candidate.action


def test_rejects_box_after_large_historical_main_advance() -> None:
    prior_closes = [25, 30, 45, 70, 110, 150, 120, 90, 60, 45]
    base_closes = [24, 26, 23, 27, 25, 29, 24, 28, 26, 30, 25, 29, 27, 31, 26, 29, 28, 30]
    closes = [*prior_closes, *base_closes, 29]
    highs = [value + 3 for value in closes]
    lows = [max(1, value - 3) for value in closes]
    amounts = [100] * len(closes)

    candidate = detect_monthly_base("000001.SZ", "测试公司", [], _series(closes, highs, lows, amounts), _gate())

    assert candidate is None


def test_red_market_gate_keeps_monthly_base_observation_only() -> None:
    closes = [24, 26, 23, 27, 25, 29, 24, 28, 26, 30, 25, 29, 27, 31, 26, 29, 28, 30, 31]
    highs = [value + 3 for value in closes]
    lows = [value - 3 for value in closes]
    amounts = [100] * len(closes)

    candidate = detect_monthly_base("000001.SZ", "测试公司", [], _series(closes, highs, lows, amounts), _gate("red"))

    assert candidate is not None
    assert "市场闸门关闭，仅列观察" in candidate.action
