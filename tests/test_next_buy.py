from ashare_mainline_radar.models import BacktestSummary, StrongStockCandidate, ThemeSnapshot, TradingGate
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
    assert report.by_theme
    assert report.by_theme[0].theme == "机器人"
    assert report.by_theme[0].plans[0].symbol == "002747.SZ"
    assert "按5个交易日波段处理" in report.primary.position_note
    assert "已有浮盈" in report.primary.position_note
    assert "亏损中不补仓" not in report.primary.position_note
    assert "跌破失效位不补仓" in report.primary.position_note


def test_red_gate_suppresses_new_buy_but_keeps_waiting_candidates() -> None:
    candidate = StrongStockCandidate(
        symbol="002747.SZ",
        name="埃斯顿",
        theme="机器人",
        last_close=20.0,
        score=90.0,
        status="趋势延续",
        ret_5d=0.05,
        ret_20d=0.18,
        amount_ratio=1.2,
        high_proximity_20d=-0.04,
    )
    theme = ThemeSnapshot(
        name="机器人",
        score=88,
        status="主线成立",
        members=8,
        breadth_5d=0.6,
        breadth_20d=0.8,
        avg_ret_5d=0.03,
        avg_ret_20d=0.12,
        amount_heat=1.1,
        catalyst_count=0,
        leaders=[],
    )
    gate = TradingGate("red", "暂停新仓", 25, 0, ["三大指数大跌"], ["观察"])

    report = build_next_buy_report([candidate], [theme], [], gate)

    assert report.primary is None
    assert report.by_theme[0].plans[0].symbol == "002747.SZ"


def test_expectation_risk_stays_in_waiting_instead_of_primary() -> None:
    candidate = StrongStockCandidate(
        symbol="002747.SZ",
        name="埃斯顿",
        theme="机器人",
        last_close=20.0,
        score=95.0,
        status="趋势延续",
        ret_5d=0.05,
        ret_20d=0.20,
        amount_ratio=1.2,
        high_proximity_20d=-0.03,
        expectation_status="利好兑现风险",
    )
    theme = ThemeSnapshot("机器人", 90, "主线成立", 8, 0.7, 0.8, 0.04, 0.15, 1.2, 0, [])

    report = build_next_buy_report([candidate], [theme], [])

    assert report.primary is None
    assert report.by_theme[0].plans[0].decision == "利好兑现风险，等待筹码稳定"
