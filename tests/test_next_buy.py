from ashare_mainline_radar.models import BacktestSummary, StrongStockCandidate, ThemeSnapshot
from ashare_mainline_radar.next_buy import build_next_buy_report


def test_build_next_buy_report_selects_primary() -> None:
    candidate = StrongStockCandidate(
        symbol="002747.SZ",
        name="埃斯顿",
        theme="机器人",
        last_close=20.0,
        score=95.0,
        status="主升确认",
        ret_5d=0.08,
        ret_20d=0.25,
        amount_ratio=1.4,
        high_proximity_20d=-0.02,
        backtest=BacktestSummary(
            symbol="002747.SZ",
            name="埃斯顿",
            theme="机器人",
            hold_days=5,
            signals=8,
            win_rate=0.625,
            avg_return=0.04,
            median_return=0.03,
            best_return=0.12,
            worst_return=-0.05,
            avg_max_drawdown=-0.03,
        ),
    )
    themes = [
        ThemeSnapshot(
            name="机器人",
            score=92.0,
            status="主线成立",
            members=10,
            breadth_5d=0.7,
            breadth_20d=0.8,
            avg_ret_5d=0.05,
            avg_ret_20d=0.15,
            amount_heat=1.2,
            catalyst_count=0,
            leaders=[],
        )
    ]
    report = build_next_buy_report([candidate], themes, [])
    assert report.primary is not None
    assert report.primary.symbol == "002747.SZ"
    assert "失效" not in report.primary.decision
