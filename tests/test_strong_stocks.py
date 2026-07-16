from dataclasses import replace

from ashare_mainline_radar.market import build_theme_snapshots, compute_symbol_snapshot
from ashare_mainline_radar.models import KlineSeries, StrongStockCandidate
from ashare_mainline_radar.strong_stocks import (
    _snapshot_passes_current_strength,
    backtest_symbol,
    build_strong_stock_report,
    fair_select_candidates,
)


def _uptrend(symbol: str) -> KlineSeries:
    close = [10 + i * 0.08 for i in range(80)]
    amount = [100 + i * 2 for i in range(80)]
    for i in range(55, 80):
        close[i] += (i - 54) * 0.08
        amount[i] += 80
    return KlineSeries(
        symbol=symbol,
        timestamp=[1780000000000 + i * 86400000 for i in range(80)],
        open=[value * 0.995 for value in close],
        high=[value * 1.02 for value in close],
        low=[value * 0.98 for value in close],
        close=close,
        volume=[1000.0 + i for i in range(80)],
        amount=amount,
    )


def test_backtest_symbol_generates_signals() -> None:
    series = _uptrend("600000.SH")
    summary = backtest_symbol("600000.SH", "测试股票", "AI算力", series, hold_days=5)
    assert summary.signals > 0
    assert summary.win_rate is not None
    assert summary.avg_return is not None


def test_build_strong_stock_report_picks_candidate() -> None:
    series = _uptrend("600000.SH")
    snapshot = compute_symbol_snapshot("600000.SH", series, instrument={"name": "测试股票"}, themes=["AI算力"])
    assert snapshot is not None
    themes = build_theme_snapshots(
        {"themes": [{"name": "AI算力", "symbols": ["600000.SH"], "vehicles": []}]},
        {"600000.SH": snapshot},
    )
    report = build_strong_stock_report(
        {"themes": [{"name": "AI算力", "symbols": ["600000.SH"], "vehicles": []}]},
        {"600000.SH": snapshot},
        {"600000.SH": series},
        themes,
        hold_days=5,
    )
    assert report.selected_themes == ["AI算力"]
    assert report.candidates
    assert report.candidates[0].backtest is not None


def test_current_candidate_must_pass_backtested_entry_quality() -> None:
    snapshot = compute_symbol_snapshot(
        "600000.SH",
        _uptrend("600000.SH"),
        instrument={"name": "测试股票"},
        themes=["AI算力"],
    )
    assert snapshot is not None
    assert _snapshot_passes_current_strength(snapshot)
    assert not _snapshot_passes_current_strength(replace(snapshot, ret_5d=0.019))
    assert not _snapshot_passes_current_strength(replace(snapshot, amount_ratio=0.99))
    assert not _snapshot_passes_current_strength(replace(snapshot, high_proximity_20d=-0.051))


def test_candidate_symbols_feed_selection_even_when_not_in_legacy_symbols() -> None:
    series = _uptrend("688331.SH")
    snapshot = compute_symbol_snapshot("688331.SH", series, instrument={"name": "荣昌生物"}, themes=["创新药"])
    assert snapshot is not None
    config = {
        "themes": [
            {
                "name": "创新药",
                "symbols": ["300760.SZ"],
                "candidate_symbols": ["688331.SH"],
                "vehicles": [],
            }
        ]
    }
    themes = build_theme_snapshots(
        {"themes": [{"name": "创新药", "scoring_symbols": ["688331.SH"]}]},
        {"688331.SH": snapshot},
    )

    report = build_strong_stock_report(
        config,
        {"688331.SH": snapshot},
        {"688331.SH": series},
        themes,
        hold_days=5,
    )

    assert [candidate.symbol for candidate in report.candidates] == ["688331.SH"]


def _candidate(symbol: str, theme: str, score: float) -> StrongStockCandidate:
    return StrongStockCandidate(
        symbol=symbol,
        name=symbol,
        theme=theme,
        last_close=10,
        score=score,
        status="主升确认",
        ret_5d=0.05,
        ret_20d=0.12,
        amount_ratio=1.2,
        high_proximity_20d=-0.02,
    )


def test_fair_selection_reserves_candidates_for_each_active_theme() -> None:
    candidates = [
        *[_candidate(f"A{index}", "半导体国产替代", 100 - index) for index in range(8)],
        _candidate("B1", "创新药", 91),
        _candidate("B2", "创新药", 90),
        _candidate("C1", "AI算力", 89),
        _candidate("C2", "AI算力", 88),
    ]

    selected = fair_select_candidates(
        candidates,
        ["半导体国产替代", "创新药", "AI算力"],
        limit=6,
        per_theme_floor=2,
    )

    assert {candidate.theme for candidate in selected} == {"半导体国产替代", "创新药", "AI算力"}
    assert sum(candidate.theme == "创新药" for candidate in selected) == 2
