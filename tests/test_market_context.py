from ashare_mainline_radar.market import compute_symbol_snapshot
from ashare_mainline_radar.market_context import build_market_pulses
from ashare_mainline_radar.models import KlineSeries


def _series(symbol: str, start: float, step: float) -> KlineSeries:
    close = [start + i * step for i in range(30)]
    return KlineSeries(
        symbol=symbol,
        timestamp=list(range(30)),
        open=[value * 0.99 for value in close],
        high=[value * 1.02 for value in close],
        low=[value * 0.98 for value in close],
        close=close,
        volume=[1000.0 + i for i in range(30)],
        amount=[100.0 + i * 3 for i in range(30)],
    )


def test_build_market_pulses_scores_group() -> None:
    snapshots = {
        "000001.SH": compute_symbol_snapshot("000001.SH", _series("000001.SH", 3000, 4), instrument={"name": "上证指数"}),
        "399006.SZ": compute_symbol_snapshot("399006.SZ", _series("399006.SZ", 2000, 6), instrument={"name": "创业板指"}),
    }
    clean = {symbol: snapshot for symbol, snapshot in snapshots.items() if snapshot is not None}
    pulses = build_market_pulses(
        {"market_context_groups": [{"name": "A股宽基环境", "symbols": ["000001.SH", "399006.SZ"]}]},
        clean,
    )
    assert len(pulses) == 1
    assert pulses[0].name == "A股宽基环境"
    assert pulses[0].members == 2
    assert pulses[0].positive_20d == 1.0
