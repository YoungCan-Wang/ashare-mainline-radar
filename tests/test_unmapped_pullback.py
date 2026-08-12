from ashare_mainline_radar.models import (
    KlineSeries,
    SymbolSnapshot,
    TradingGate,
    UnmappedStrengthReport,
)
from ashare_mainline_radar.unmapped_pullback import build_unmapped_pullback_report


def _series_from_closes(symbol: str, closes: list[float]) -> KlineSeries:
    n = len(closes)
    highs = [price * 1.01 for price in closes]
    lows = [price * 0.99 for price in closes]
    return KlineSeries(
        symbol=symbol,
        timestamp=list(range(n)),
        open=list(closes),
        high=highs,
        low=lows,
        close=list(closes),
        volume=[1_000_000.0] * n,
        amount=[10_000_000.0] * n,
    )


def _pullback_closes() -> list[float]:
    # Base ~10, advance to 12 (+20%), pullback to 11 (-8.3% from high), reclaim to 11.5.
    base = [10.0 + i * 0.01 for i in range(20)]
    rally = [10.2 + i * 0.12 for i in range(15)]
    peak = [12.0, 12.1, 12.2]
    pullback = [12.0, 11.7, 11.4, 11.2, 11.15]
    reclaim = [11.2, 11.35, 11.45, 11.55]
    return base + rally + peak + pullback + reclaim


def _snapshot(symbol: str, name: str = "测试公司") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        name=name,
        themes=[],
        last_close=11.55,
        ret_1d=0.01,
        ret_5d=0.04,
        ret_20d=0.12,
        amount_ma5=120,
        amount_ma20=100,
        amount_ratio=1.2,
        high_proximity_20d=-0.03,
        drawdown_20d=-0.03,
        score=88,
        status="趋势延续",
        relative_percentile=92.0,
    )


def _constructive_series(symbol: str) -> KlineSeries:
    series = _series_from_closes(symbol, _pullback_closes())
    pullback_start = len(series.close) - 9
    for idx in range(pullback_start, pullback_start + 5):
        series.low[idx] = series.close[idx] * 0.93
    series.high[pullback_start - 1] = 12.4
    return series


def test_red_gate_blocks_buyable() -> None:
    symbol = "000001.SZ"
    series = _constructive_series(symbol)
    snapshot = _snapshot(symbol)
    snapshot.last_close = series.close[-1]
    gate = TradingGate("red", "暂停新仓", 20, 0.0, ["破位"], ["观察"])
    report = build_unmapped_pullback_report(
        snapshots={symbol: snapshot},
        klines={symbol: series},
        instruments={symbol: {"name": "测试公司"}},
        trading_gate=gate,
        unmapped_strength=UnmappedStrengthReport(candidates=[snapshot], scanned_unmapped=1),
    )
    assert report.candidates
    assert report.buyable_now == []
    assert all(not item.buyable_now for item in report.candidates)
    assert all(item.max_position_fraction == 0 for item in report.candidates)


def test_happy_path_pullback_plan_fields() -> None:
    symbol = "000001.SZ"
    series = _constructive_series(symbol)
    snapshot = _snapshot(symbol)
    snapshot.last_close = series.close[-1]
    gate = TradingGate("green", "允许寻找买点", 70, 1 / 3, ["ok"], ["分批"])
    report = build_unmapped_pullback_report(
        snapshots={symbol: snapshot},
        klines={symbol: series},
        instruments={symbol: {"name": "测试公司"}},
        trading_gate=gate,
        unmapped_strength=UnmappedStrengthReport(candidates=[snapshot], scanned_unmapped=1),
    )
    assert report.buyable_now
    primary = report.buyable_now[0]
    assert primary.symbol == symbol
    assert primary.buyable_now is True
    assert primary.entry_zone_low is not None
    assert primary.entry_zone_high is not None
    assert primary.confirm_price is not None
    assert primary.stop_price is not None
    assert primary.max_position_fraction > 0
    assert primary.entry_plan
    assert primary.invalidation


def test_excludes_st() -> None:
    st_symbol = "000003.SZ"
    ok_symbol = "000001.SZ"
    st_series = _constructive_series(st_symbol)
    ok_series = _constructive_series(ok_symbol)
    st_snap = _snapshot(st_symbol, "*ST测试")
    ok_snap = _snapshot(ok_symbol)
    ok_snap.last_close = ok_series.close[-1]
    gate = TradingGate("green", "允许寻找买点", 70, 1 / 3, [], [])
    report = build_unmapped_pullback_report(
        snapshots={st_symbol: st_snap, ok_symbol: ok_snap},
        klines={st_symbol: st_series, ok_symbol: ok_series},
        instruments={st_symbol: {"name": "*ST测试"}, ok_symbol: {"name": "测试公司"}},
        trading_gate=gate,
        unmapped_strength=UnmappedStrengthReport(candidates=[st_snap, ok_snap], scanned_unmapped=2),
    )
    symbols = {item.symbol for item in report.candidates}
    assert st_symbol not in symbols
    assert ok_symbol in symbols
