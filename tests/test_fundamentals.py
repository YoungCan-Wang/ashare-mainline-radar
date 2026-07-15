from ashare_mainline_radar.fundamentals import (
    apply_fundamental_overlay,
    apply_theme_fundamental_overlay,
    build_fundamental_report,
)
from ashare_mainline_radar.models import (
    AccumulationReport,
    BacktestSummary,
    StrongStockCandidate,
    StrongStockReport,
    ThemeSnapshot,
)


def _candidate(symbol: str, score: float = 80.0) -> StrongStockCandidate:
    return StrongStockCandidate(
        symbol=symbol,
        name=symbol,
        theme="机器人",
        last_close=20.0,
        score=score,
        status="主升确认",
        ret_5d=0.05,
        ret_20d=0.15,
        amount_ratio=1.2,
        high_proximity_20d=-0.02,
        backtest=BacktestSummary(
            symbol=symbol,
            name=symbol,
            theme="机器人",
            hold_days=5,
            signals=5,
            win_rate=0.6,
            avg_return=0.03,
            median_return=0.02,
            best_return=0.1,
            worst_return=-0.05,
            avg_max_drawdown=-0.03,
        ),
    )


def test_fundamental_report_uses_same_period_trend_and_reorders_candidates() -> None:
    raw = {
        "GOOD.SZ": [
            {"period_end": "2025-03-31", "revenue_yoy": 8, "net_income_yoy": 10},
            {
                "period_end": "2026-03-31",
                "announce_date": "2026-04-20",
                "revenue_yoy": 28,
                "net_income_yoy": 45,
                "roe_diluted": 12,
                "ocfps": 0.8,
                "bps": 5,
            },
        ],
        "WEAK.SZ": [
            {
                "period_end": "2026-03-31",
                "revenue_yoy": -20,
                "net_income_yoy": -50,
                "roe_diluted": 2,
                "ocfps": -0.5,
                "bps": 4,
            }
        ],
    }
    report = build_fundamental_report(raw, {"GOOD.SZ": 20, "WEAK.SZ": 20}, ["GOOD.SZ", "WEAK.SZ"])
    good = next(item for item in report.snapshots if item.symbol == "GOOD.SZ")
    assert good.revenue_yoy_change == 20
    assert good.net_income_yoy_change == 35
    assert good.price_to_book == 4
    assert good.status == "基本面兑现"

    strong = StrongStockReport(
        selected_themes=["机器人"],
        hold_days=5,
        candidates=[_candidate("WEAK.SZ", 83), _candidate("GOOD.SZ", 80)],
    )
    apply_fundamental_overlay(strong, AccumulationReport(candidates=[]), report, 10, 10)
    assert strong.candidates[0].symbol == "GOOD.SZ"
    assert strong.candidates[1].fundamental_status == "基本面拖累"


def test_fundamental_report_allows_empty_degraded_input() -> None:
    report = build_fundamental_report({}, {}, ["000001.SZ"])
    assert report.covered_symbols == 0
    assert report.requested_symbols == 1


def test_negative_roe_cannot_be_classified_as_fundamental_delivery() -> None:
    raw = {
        "LOSS.SZ": [
            {
                "period_end": "2026-03-31",
                "revenue_yoy": 45,
                "net_income_yoy": 300,
                "roe_diluted": -0.3,
                "ocfps": 0.1,
                "bps": 3,
            }
        ]
    }
    report = build_fundamental_report(raw, {"LOSS.SZ": 12}, ["LOSS.SZ"])
    item = report.snapshots[0]
    assert item.score <= 55
    assert item.status != "基本面兑现"


def test_negative_operating_cash_flow_requires_quality_confirmation() -> None:
    raw = {
        "CASH.SZ": [
            {
                "period_end": "2026-03-31",
                "revenue_yoy": 50,
                "net_income_yoy": 100,
                "roe_diluted": 5,
                "ocfps": -0.5,
                "bps": 3,
            }
        ]
    }
    report = build_fundamental_report(raw, {"CASH.SZ": 12}, ["CASH.SZ"])
    item = report.snapshots[0]
    assert item.score <= 72
    assert item.status == "兑现待质量确认"


def test_halfway_theme_needs_broad_fundamental_delivery_before_confirmation() -> None:
    raw = {
        symbol: [
            {
                "period_end": "2026-03-31",
                "revenue_yoy": 30,
                "net_income_yoy": 50,
                "roe_diluted": 12,
                "ocfps": 0.8,
                "bps": 5,
            }
        ]
        for symbol in ("A.SZ", "B.SZ")
    }
    report = build_fundamental_report(raw, {"A.SZ": 20, "B.SZ": 20}, ["A.SZ", "B.SZ"])
    theme = ThemeSnapshot(
        name="机器人",
        score=80,
        status="主线成立",
        members=3,
        breadth_5d=0.6,
        breadth_20d=0.7,
        avg_ret_5d=0.03,
        avg_ret_20d=0.1,
        amount_heat=1.1,
        catalyst_count=0,
        leaders=[],
        price_phase="半山腰待验证",
    )

    apply_theme_fundamental_overlay(
        [theme],
        report,
        {"A.SZ": ["机器人"], "B.SZ": ["机器人"], "C.SZ": ["机器人"]},
        {"A.SZ", "B.SZ", "C.SZ"},
    )

    assert theme.price_phase == "半山腰兑现"
    assert theme.fundamental_coverage == 2 / 3
    assert theme.fundamental_confirmed_ratio == 1
