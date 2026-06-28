from ashare_mainline_radar.market import build_theme_snapshots, compute_symbol_snapshot
from ashare_mainline_radar.models import KlineSeries


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
