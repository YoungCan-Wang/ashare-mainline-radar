from ashare_mainline_radar.models import (
    FundamentalReport,
    FundamentalSnapshot,
    KlineSeries,
    SymbolSnapshot,
    TradingGate,
    UnmappedStrengthReport,
)
from ashare_mainline_radar.unmapped_pullback import (
    analyze_pullback_structure,
    build_unmapped_pullback_report,
)


def _series_from_closes(symbol: str, closes: list[float]) -> KlineSeries:
    n = len(closes)
    highs = [price * 1.01 for price in closes]
    lows = [price * 0.99 for price in closes]
    # Make pullback visible in high/low extremes for constructive paths.
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
    rally = [10.2 + i * 0.12 for i in range(15)]  # up to ~11.88
    peak = [12.0, 12.1, 12.2]
    pullback = [12.0, 11.7, 11.4, 11.2, 11.15]
    reclaim = [11.2, 11.35, 11.45, 11.55]
    return base + rally + peak + pullback + reclaim


def _rocket_closes() -> list[float]:
    # Smooth one-way advance with tiny dips.
    return [10.0 + i * 0.08 for i in range(45)]


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


def test_analyze_pullback_structure_detects_reclaim() -> None:
    series = _series_from_closes("000001.SZ", _pullback_closes())
    # Deepen the pullback lows so max_pullback <= -6%.
    pullback_start = len(series.close) - 9
    for idx in range(pullback_start, pullback_start + 5):
        series.low[idx] = series.close[idx] * 0.93
    series.high = [max(h, c) for h, c in zip(series.high, series.close)]
    # Ensure interim high stays elevated.
    peak_idx = pullback_start - 1
    series.high[peak_idx] = 12.4
    structure = analyze_pullback_structure(series)
    assert structure is not None
    assert structure.had_constructive_pullback
    assert structure.style_tag == "pullback_reclaim"


def test_analyze_rocket_is_watch_only_style() -> None:
    series = _series_from_closes("000002.SZ", _rocket_closes())
    structure = analyze_pullback_structure(series)
    assert structure is not None
    assert structure.style_tag == "rocket_watch"
    assert not structure.had_constructive_pullback


def test_build_report_marks_buyable_pullback_and_zones() -> None:
    symbol = "000001.SZ"
    closes = _pullback_closes()
    series = _series_from_closes(symbol, closes)
    pullback_start = len(series.close) - 9
    for idx in range(pullback_start, pullback_start + 5):
        series.low[idx] = series.close[idx] * 0.93
    series.high[pullback_start - 1] = 12.4
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
    assert "试错" in primary.gate_action or "买点" in primary.gate_action


def test_red_gate_suppresses_buyable_plans() -> None:
    symbol = "000001.SZ"
    series = _series_from_closes(symbol, _pullback_closes())
    pullback_start = len(series.close) - 9
    for idx in range(pullback_start, pullback_start + 5):
        series.low[idx] = series.close[idx] * 0.93
    series.high[pullback_start - 1] = 12.4
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
    assert "红色" in report.notes[-1] or any("红色" in note for note in report.notes)


def test_orange_gate_caps_position_and_prefers_pullback() -> None:
    pullback_symbol = "000001.SZ"
    rocket_symbol = "000002.SZ"
    pullback_series = _series_from_closes(pullback_symbol, _pullback_closes())
    pullback_start = len(pullback_series.close) - 9
    for idx in range(pullback_start, pullback_start + 5):
        pullback_series.low[idx] = pullback_series.close[idx] * 0.93
    pullback_series.high[pullback_start - 1] = 12.4
    rocket_series = _series_from_closes(rocket_symbol, _rocket_closes())
    pullback_snap = _snapshot(pullback_symbol)
    pullback_snap.last_close = pullback_series.close[-1]
    rocket_snap = _snapshot(rocket_symbol, "火箭公司")
    rocket_snap.last_close = rocket_series.close[-1]
    gate = TradingGate("orange", "只准试错仓", 45, 1 / 3, ["谨慎"], ["小仓"])
    report = build_unmapped_pullback_report(
        snapshots={pullback_symbol: pullback_snap, rocket_symbol: rocket_snap},
        klines={pullback_symbol: pullback_series, rocket_symbol: rocket_series},
        instruments={
            pullback_symbol: {"name": "测试公司"},
            rocket_symbol: {"name": "火箭公司"},
        },
        trading_gate=gate,
        unmapped_strength=UnmappedStrengthReport(
            candidates=[pullback_snap, rocket_snap],
            scanned_unmapped=2,
        ),
    )
    by_symbol = {item.symbol: item for item in report.candidates}
    assert by_symbol[rocket_symbol].buyable_now is False
    assert by_symbol[rocket_symbol].style_tag == "rocket_watch"
    if by_symbol[pullback_symbol].buyable_now:
        assert by_symbol[pullback_symbol].max_position_fraction <= 0.06


def test_excludes_st_and_marks_bj_ipo_speculative() -> None:
    st_symbol = "000003.SZ"
    bj_symbol = "830001.BJ"
    st_series = _series_from_closes(st_symbol, _pullback_closes())
    bj_series = _series_from_closes(bj_symbol, _pullback_closes()[:40])
    st_snap = _snapshot(st_symbol, "*ST测试")
    bj_snap = _snapshot(bj_symbol, "北交次新")
    bj_snap.last_close = bj_series.close[-1]
    gate = TradingGate("green", "允许寻找买点", 70, 1 / 3, [], [])
    report = build_unmapped_pullback_report(
        snapshots={st_symbol: st_snap, bj_symbol: bj_snap},
        klines={st_symbol: st_series, bj_symbol: bj_series},
        instruments={st_symbol: {"name": "*ST测试"}, bj_symbol: {"name": "北交次新"}},
        trading_gate=gate,
        unmapped_strength=UnmappedStrengthReport(candidates=[st_snap, bj_snap], scanned_unmapped=2),
    )
    symbols = {item.symbol for item in report.candidates}
    assert st_symbol not in symbols
    assert bj_symbol in symbols
    bj = next(item for item in report.candidates if item.symbol == bj_symbol)
    assert bj.style_tag == "bj_ipo_speculative"
    assert bj.buyable_now is False


def test_fundamental_drag_blocks_buyable() -> None:
    symbol = "000001.SZ"
    series = _series_from_closes(symbol, _pullback_closes())
    pullback_start = len(series.close) - 9
    for idx in range(pullback_start, pullback_start + 5):
        series.low[idx] = series.close[idx] * 0.93
    series.high[pullback_start - 1] = 12.4
    snapshot = _snapshot(symbol)
    snapshot.last_close = series.close[-1]
    fundamentals = FundamentalReport(
        snapshots=[
            FundamentalSnapshot(
                symbol=symbol,
                period_end="2025-12-31",
                announce_date="2026-03-01",
                revenue_yoy=-0.2,
                net_income_yoy=-0.3,
                roe=0.02,
                ocfps=None,
                bps=None,
                price_to_book=None,
                revenue_yoy_change=-0.1,
                net_income_yoy_change=-0.1,
                score=30.0,
                status="基本面拖累",
            )
        ],
        covered_symbols=1,
        requested_symbols=1,
    )
    gate = TradingGate("green", "允许寻找买点", 70, 1 / 3, [], [])
    report = build_unmapped_pullback_report(
        snapshots={symbol: snapshot},
        klines={symbol: series},
        instruments={symbol: {"name": "测试公司"}},
        trading_gate=gate,
        unmapped_strength=UnmappedStrengthReport(candidates=[snapshot], scanned_unmapped=1),
        fundamentals=fundamentals,
    )
    assert report.candidates
    assert report.buyable_now == []
    assert "基本面" in report.candidates[0].decision
