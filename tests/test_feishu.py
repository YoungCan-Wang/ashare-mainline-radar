import json

from ashare_mainline_radar.feishu import FeishuStatus, build_feishu_card, build_feishu_text, write_feishu_status
from ashare_mainline_radar.models import (
    AccumulationReport,
    BacktestSummary,
    FundamentalReport,
    NextBuyPlan,
    NextBuyReport,
    PolicySignalReport,
    RadarReport,
    StrongStockReport,
    StrongStockCandidate,
    TargetPriceReport,
)


def test_build_feishu_text_minimal_report() -> None:
    report = RadarReport(
        generated_at="2026-06-29T00:00:00+00:00",
        data_as_of="2026-06-26",
        mode="curated",
        universe="CN_Equity_A",
        scanned_symbols=0,
        data_source="test",
        themes=[],
        market_pulses=[],
        strong_stocks=StrongStockReport(selected_themes=[], hold_days=5, candidates=[]),
        next_buy=NextBuyReport(primary=None),
        accumulation=AccumulationReport(candidates=[]),
        policy_signals=PolicySignalReport(signals=[], total_policy_items=0, matched_policy_items=0),
        target_prices=TargetPriceReport(estimates=[]),
        fundamentals=FundamentalReport(snapshots=[], covered_symbols=0, requested_symbols=0),
        leader_tape=[],
        market_watchlist=[],
        intel_items=[],
        source_statuses=[],
        warnings=[],
    )
    text = build_feishu_text(report)
    assert "A股市场主线雷达" in text
    assert "2026-06-26" in text
    card = build_feishu_card(report)
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "red"
    contents = "\n".join(
        element.get("content", "")
        for element in card["body"]["elements"]
        if element.get("tag") == "markdown"
    )
    assert "可尝试建仓" in contents
    assert "已有仓位可继续持有" in contents
    assert "10-20个交易日" in contents


def test_write_feishu_status(tmp_path) -> None:
    path = write_feishu_status(tmp_path / "status.json", FeishuStatus(status="failed", code=19007, message="Bot Not Enabled"))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["code"] == 19007


def test_card_allows_etf_attempt_without_company_fundamentals() -> None:
    candidate = StrongStockCandidate(
        symbol="588200.SH",
        name="科创芯片ETF嘉实",
        theme="半导体国产替代",
        last_close=1.2,
        score=85,
        status="突破观察",
        ret_5d=0.05,
        ret_20d=0.12,
        amount_ratio=1.2,
        high_proximity_20d=-0.02,
        backtest=BacktestSummary(
            symbol="588200.SH",
            name="科创芯片ETF嘉实",
            theme="半导体国产替代",
            hold_days=15,
            signals=6,
            win_rate=0.67,
            avg_return=0.05,
            median_return=0.04,
            best_return=0.12,
            worst_return=-0.04,
            avg_max_drawdown=-0.03,
        ),
    )
    plan = NextBuyPlan(
        symbol=candidate.symbol,
        name=candidate.name,
        theme=candidate.theme,
        decision="突破确认候选",
        priority_score=82,
        last_close=1.2,
        entry_plan="放量站上1.22后确认。",
        invalidation="跌破1.12退出。",
        position_note="首笔试错。",
    )
    report = RadarReport(
        generated_at="2026-07-11T00:00:00+00:00",
        data_as_of="2026-07-10",
        mode="universe",
        universe="CN_Equity_A",
        scanned_symbols=1200,
        data_source="test",
        themes=[],
        market_pulses=[],
        strong_stocks=StrongStockReport(selected_themes=[candidate.theme], hold_days=15, candidates=[candidate]),
        next_buy=NextBuyReport(primary=plan),
        accumulation=AccumulationReport(candidates=[]),
        policy_signals=PolicySignalReport(signals=[], total_policy_items=0, matched_policy_items=0),
        target_prices=TargetPriceReport(estimates=[]),
        fundamentals=FundamentalReport(snapshots=[], covered_symbols=0, requested_symbols=0),
        leader_tape=[],
        market_watchlist=[],
        intel_items=[],
        source_statuses=[],
        warnings=[],
    )
    card = build_feishu_card(report)
    contents = "\n".join(
        element.get("content", "")
        for element in card["body"]["elements"]
        if element.get("tag") == "markdown"
    )
    assert "科创芯片ETF嘉实" in contents
    assert "ETF分散载体" in contents
    assert "15日回测" in contents
