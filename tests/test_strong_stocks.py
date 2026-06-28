from ashare_mainline_radar.market import build_theme_snapshots, compute_symbol_snapshot
from ashare_mainline_radar.models import KlineSeries
from ashare_mainline_radar.strong_stocks import backtest_symbol, build_strong_stock_report


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
