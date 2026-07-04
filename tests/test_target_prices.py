from ashare_mainline_radar.accumulation import build_accumulation_report
from ashare_mainline_radar.market import compute_symbol_snapshot
from ashare_mainline_radar.models import (
    BacktestSummary,
    IntelItem,
    KlineSeries,
    StrongStockCandidate,
    StrongStockReport,
    ThemeSnapshot,
)
from ashare_mainline_radar.target_prices import build_target_price_report


def _series(symbol: str) -> KlineSeries:
    close = [10.0 + i * 0.08 for i in range(80)]
    for idx in range(50, 80):
        close[idx] += (idx - 49) * 0.08
    return KlineSeries(
        symbol=symbol,
        timestamp=[1780000000000 + i * 86400000 for i in range(80)],
        open=[value * 0.995 for value in close],
        high=[value * 1.025 for value in close],
        low=[value * 0.975 for value in close],
        close=close,
        volume=[1000.0 + i for i in range(80)],
        amount=[100.0 + i * 3 for i in range(80)],
    )


def test_build_target_price_report_for_strong_candidate_extracts_research_target() -> None:
    series = _series("002747.SZ")
    candidate = StrongStockCandidate(
        symbol="002747.SZ",
        name="埃斯顿",
        theme="机器人",
        last_close=series.close[-1],
        score=92.0,
        status="突破观察",
        ret_5d=0.08,
        ret_20d=0.2,
        amount_ratio=1.2,
        high_proximity_20d=-0.02,
        backtest=BacktestSummary(
            symbol="002747.SZ",
            name="埃斯顿",
            theme="机器人",
            hold_days=5,
            signals=8,
            win_rate=0.625,
            avg_return=0.04,
            median_return=0.035,
            best_return=0.12,
            worst_return=-0.05,
            avg_max_drawdown=-0.03,
        ),
    )
    themes = [
        ThemeSnapshot(
            name="机器人",
            score=88.0,
            status="主线成立",
            members=5,
            breadth_5d=0.8,
            breadth_20d=0.8,
            avg_ret_5d=0.05,
            avg_ret_20d=0.12,
            amount_heat=1.1,
            catalyst_count=0,
            leaders=[],
        )
    ]
    intel_items = [
        IntelItem(
            source="local:report.md",
            title="埃斯顿深度报告",
            summary="维持买入评级，目标价为28.50元。",
            tags=["research"],
        )
    ]

    report = build_target_price_report(
        StrongStockReport(selected_themes=["机器人"], hold_days=5, candidates=[candidate]),
        build_accumulation_report({}, {}, []),
        {"002747.SZ": series},
        intel_items,
        themes,
    )

    assert report.estimates
    estimate = report.estimates[0]
    assert estimate.target_low > estimate.last_close
    assert estimate.target_high >= estimate.target_low
    assert estimate.research_targets[0].target_low == 28.5
    assert estimate.confidence == "中高"
    assert estimate.downside_to_stop > -0.12


def test_build_target_price_report_for_accumulation_candidate() -> None:
    close = [20.0 - i * 0.08 for i in range(35)]
    close.extend([13.8 - i * 0.04 for i in range(15)])
    close.extend([12.9 + i * 0.065 for i in range(30)])
    series = KlineSeries(
        symbol="600000.SH",
        timestamp=[1780000000000 + i * 86400000 for i in range(80)],
        open=[value * 0.995 for value in close],
        high=[value * 1.025 for value in close],
        low=[value * 0.975 for value in close],
        close=close,
        volume=[1000.0 + i for i in range(80)],
        amount=[100.0 for _ in range(50)] + [115.0 + i * 2.0 for i in range(10)] + [145.0 + i * 3.0 for i in range(20)],
    )
    snapshot = compute_symbol_snapshot("600000.SH", series, instrument={"name": "测试股票"}, themes=["AI算力"])
    assert snapshot is not None
    accumulation = build_accumulation_report({"600000.SH": snapshot}, {"600000.SH": series}, [])

    report = build_target_price_report(
        StrongStockReport(selected_themes=[], hold_days=5, candidates=[]),
        accumulation,
        {"600000.SH": series},
        [],
        [],
    )

    assert report.estimates
    assert report.estimates[0].candidate_type == "低位资金介入"
    assert report.estimates[0].target_low > report.estimates[0].last_close
