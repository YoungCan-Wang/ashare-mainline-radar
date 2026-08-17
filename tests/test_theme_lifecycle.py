from ashare_mainline_radar.models import ThemeLifecycleReport, ThemeSnapshot, TradingGate
from ashare_mainline_radar.theme_lifecycle import (
    LifecyclePoint,
    apply_theme_independence,
    trace_theme_lifecycle,
)


def _theme(status: str = "主线成立") -> ThemeSnapshot:
    return ThemeSnapshot(
        name="创新药",
        score=91,
        status=status,
        members=12,
        breadth_5d=0.2,
        breadth_20d=0.8,
        avg_ret_5d=-0.02,
        avg_ret_20d=0.12,
        amount_heat=0.98,
        catalyst_count=0,
        leaders=[],
    )


def _point(
    date: str,
    status: str,
    breadth_5d: float,
    breadth_20d: float,
    ret_5d: float,
    ret_20d: float,
    amount_heat: float,
) -> LifecyclePoint:
    return LifecyclePoint(
        date=date,
        status=status,
        score=80,
        breadth_5d=breadth_5d,
        breadth_20d=breadth_20d,
        avg_ret_5d=ret_5d,
        avg_ret_20d=ret_20d,
        amount_heat=amount_heat,
    )


def test_lifecycle_records_start_confirmation_and_acceleration() -> None:
    points = [
        _point("2026-06-22", "弱势/等待", 0.4, 0.3, 0.00, -0.02, 0.95),
        _point("2026-06-23", "轮动观察", 0.75, 0.3, 0.02, 0.00, 1.05),
        _point("2026-06-24", "主线成立", 0.8, 0.60, 0.05, -0.02, 1.18),
        _point("2026-06-30", "主线成立", 0.8, 0.65, 0.04, 0.08, 1.25),
        _point("2026-07-01", "主线成立", 1.0, 0.75, 0.09, 0.12, 1.35),
    ]

    signal = trace_theme_lifecycle("创新药", points, _theme())

    assert signal is not None
    assert signal.stage == "主升加速"
    assert signal.started_at == "2026-06-23"
    assert signal.confirmed_at == "2026-06-30"
    assert signal.stage_since == "2026-07-01"


def test_confirmed_theme_survives_single_day_pullback() -> None:
    points = [
        _point("2026-06-23", "轮动观察", 0.75, 0.3, 0.02, 0.00, 1.05),
        _point("2026-06-30", "主线成立", 0.8, 0.65, 0.07, 0.08, 1.25),
        _point("2026-07-10", "主线成立", 0.8, 0.8, 0.06, 0.15, 1.18),
        _point("2026-07-13", "主线成立", 0.1, 0.8, -0.03, 0.12, 0.96),
    ]

    signal = trace_theme_lifecycle("创新药", points, _theme(status="主线成立"))

    assert signal is not None
    assert signal.stage == "主线回踩"
    assert signal.started_at == "2026-06-23"
    assert signal.confirmed_at == "2026-06-30"
    assert signal.stage_since == "2026-07-13"


def test_failed_false_start_resets_before_next_round() -> None:
    points = [
        _point("2026-05-07", "主线候选", 0.7, 0.4, 0.03, 0.01, 1.10),
        _point("2026-05-08", "弱势/等待", 0.3, 0.3, -0.02, -0.01, 0.9),
        _point("2026-05-11", "弱势/等待", 0.2, 0.2, -0.03, -0.02, 0.9),
        _point("2026-05-12", "弱势/等待", 0.2, 0.2, -0.04, -0.03, 0.9),
        _point("2026-06-23", "轮动观察", 0.75, 0.3, 0.02, 0.00, 1.05),
        _point("2026-06-30", "主线成立", 0.8, 0.65, 0.07, 0.08, 1.25),
    ]

    signal = trace_theme_lifecycle("创新药", points, _theme())

    assert signal is not None
    assert signal.started_at == "2026-06-23"
    assert signal.confirmed_at == "2026-06-30"


def test_confirm_to_continuation_keeps_stage_since() -> None:
    points = [
        _point("2026-08-12", "轮动观察", 0.75, 0.3, 0.02, 0.00, 1.05),
        _point("2026-08-14", "主线成立", 0.8, 0.65, 0.04, 0.08, 1.25),
        _point("2026-08-15", "主线成立", 0.75, 0.62, 0.03, 0.07, 1.15),
        _point("2026-08-17", "主线成立", 0.70, 0.60, 0.025, 0.06, 1.10),
    ]

    signal = trace_theme_lifecycle("光伏", points, _theme())

    assert signal is not None
    assert signal.stage == "主线延续"
    assert signal.started_at == "2026-08-12"
    assert signal.confirmed_at == "2026-08-14"
    assert signal.stage_since == "2026-08-14"
    assert signal.previous_stage == "主线确认"


def test_weak_market_can_keep_a_genuinely_independent_mainline() -> None:
    theme = _theme()
    theme.breadth_5d = 0.8
    theme.breadth_20d = 0.7
    theme.avg_ret_5d = 0.12
    theme.amount_heat = 1.4
    signal = trace_theme_lifecycle(
        "创新药",
        [
            _point("2026-06-23", "轮动观察", 0.75, 0.3, 0.02, 0.00, 1.05),
            _point("2026-06-29", "主线成立", 0.8, 0.7, 0.12, 0.15, 1.4),
        ],
        theme,
    )
    assert signal is not None
    report = ThemeLifecycleReport(signals=[signal], history_days=45)
    gate = TradingGate(
        level="orange",
        state="只准试错仓",
        score=55,
        max_initial_position_fraction=0.1,
        median_stock_return_5d=0.01,
    )

    apply_theme_independence(report, [theme], gate)

    assert signal.independence_status == "逆势独立主线"
    assert signal.relative_strength_5d == 0.11
    assert signal.independent_score >= 68
