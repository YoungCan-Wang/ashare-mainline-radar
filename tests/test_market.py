from ashare_mainline_radar.market import (
    build_theme_snapshots,
    compute_symbol_snapshot,
    normalize_symbol_scores,
)
from ashare_mainline_radar.models import KlineSeries, SymbolSnapshot


def _series(symbol: str, start: float, step: float, amount_base: float = 100.0) -> KlineSeries:
    close = [start + i * step for i in range(30)]
    return KlineSeries(
        symbol=symbol,
        timestamp=list(range(30)),
        open=[value * 0.99 for value in close],
        high=[value * 1.02 for value in close],
        low=[value * 0.98 for value in close],
        close=close,
        volume=[1000.0 + i for i in range(30)],
        amount=[amount_base + i * 4 for i in range(30)],
    )


def test_compute_symbol_snapshot_scores_uptrend() -> None:
    snapshot = compute_symbol_snapshot(
        "600000.SH",
        _series("600000.SH", 10.0, 0.2),
        instrument={"name": "测试股票"},
        themes=["AI算力"],
    )
    assert snapshot is not None
    assert snapshot.name == "测试股票"
    assert snapshot.ret_20d is not None and snapshot.ret_20d > 0
    assert snapshot.score > 60
    assert snapshot.status in {"主升确认", "突破观察", "趋势延续"}


def test_build_theme_snapshots_ranks_theme() -> None:
    snapshots = {
        "600000.SH": compute_symbol_snapshot("600000.SH", _series("600000.SH", 10, 0.2), themes=["AI算力"]),
        "000001.SZ": compute_symbol_snapshot("000001.SZ", _series("000001.SZ", 20, 0.1), themes=["AI算力"]),
    }
    clean = {symbol: snapshot for symbol, snapshot in snapshots.items() if snapshot is not None}
    themes = build_theme_snapshots(
        {
            "themes": [
                {
                    "name": "AI算力",
                    "valuation_style": "growth",
                    "symbols": ["600000.SH", "000001.SZ"],
                    "vehicles": [],
                }
            ]
        },
        clean,
        {"AI算力": 2},
    )
    assert len(themes) == 1
    assert themes[0].name == "AI算力"
    assert themes[0].score > 60
    assert themes[0].valuation_style == "growth"


def test_theme_scoring_symbols_keep_broad_candidates_out_of_breadth() -> None:
    snapshots = {
        "600000.SH": compute_symbol_snapshot("600000.SH", _series("600000.SH", 10, 0.2)),
        "000001.SZ": compute_symbol_snapshot("000001.SZ", _series("000001.SZ", 20, 0.1)),
        "300000.SZ": compute_symbol_snapshot("300000.SZ", _series("300000.SZ", 30, -0.3)),
    }
    clean = {symbol: snapshot for symbol, snapshot in snapshots.items() if snapshot is not None}

    themes = build_theme_snapshots(
        {
            "themes": [
                {
                    "name": "创新药",
                    "symbols": ["600000.SH", "000001.SZ", "300000.SZ"],
                    "scoring_symbols": ["600000.SH", "000001.SZ"],
                    "vehicles": [],
                }
            ]
        },
        clean,
    )

    assert themes[0].members == 2
    assert themes[0].breadth_20d == 1


def _snapshot(symbol: str, score: float, ret_20d: float) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        name=symbol,
        themes=[],
        last_close=10,
        ret_1d=0.01,
        ret_5d=0.04,
        ret_20d=ret_20d,
        amount_ma5=120,
        amount_ma20=100,
        amount_ratio=1.2,
        high_proximity_20d=-0.02,
        drawdown_20d=-0.02,
        score=score,
        status="突破观察",
    )


def test_symbol_scores_include_cross_sectional_percentile_without_saturating() -> None:
    snapshots = {
        "000001.SZ": _snapshot("000001.SZ", 100, 0.2),
        "000002.SZ": _snapshot("000002.SZ", 80, 0.1),
        "000003.SZ": _snapshot("000003.SZ", 60, 0.05),
    }

    normalize_symbol_scores(snapshots)

    assert snapshots["000001.SZ"].relative_percentile == 100
    assert snapshots["000001.SZ"].score < 100
    assert snapshots["000003.SZ"].relative_percentile == 0


def test_theme_score_penalizes_single_leader_concentration() -> None:
    concentrated = {
        "000001.SZ": _snapshot("000001.SZ", 90, 0.80),
        "000002.SZ": _snapshot("000002.SZ", 80, 0.02),
        "000003.SZ": _snapshot("000003.SZ", 80, 0.02),
        "000004.SZ": _snapshot("000004.SZ", 80, 0.02),
    }
    themes = build_theme_snapshots(
        {"themes": [{"name": "集中主题", "symbols": list(concentrated), "vehicles": []}]},
        concentrated,
    )

    assert themes[0].leader_concentration is not None and themes[0].leader_concentration > 0.9
    assert any("集中度扣分" in item for item in themes[0].evidence)
