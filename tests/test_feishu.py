from ashare_mainline_radar.feishu import build_feishu_text
from ashare_mainline_radar.models import RadarReport, StrongStockReport


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
        leader_tape=[],
        market_watchlist=[],
        intel_items=[],
        source_statuses=[],
        warnings=[],
    )
    text = build_feishu_text(report)
    assert "A股市场主线雷达" in text
    assert "2026-06-26" in text
