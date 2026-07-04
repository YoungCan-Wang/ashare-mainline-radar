import json

from ashare_mainline_radar.feishu import FeishuStatus, build_feishu_text, write_feishu_status
from ashare_mainline_radar.models import AccumulationReport, NextBuyReport, PolicySignalReport, RadarReport, StrongStockReport


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
        leader_tape=[],
        market_watchlist=[],
        intel_items=[],
        source_statuses=[],
        warnings=[],
    )
    text = build_feishu_text(report)
    assert "A股市场主线雷达" in text
    assert "2026-06-26" in text


def test_write_feishu_status(tmp_path) -> None:
    path = write_feishu_status(tmp_path / "status.json", FeishuStatus(status="failed", code=19007, message="Bot Not Enabled"))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["code"] == 19007
