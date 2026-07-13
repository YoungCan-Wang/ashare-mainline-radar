from ashare_mainline_radar.market_context import build_market_pulses
from ashare_mainline_radar.models import SymbolSnapshot
from ashare_mainline_radar.risk_gate import build_trading_gate


def _snapshot(symbol: str, ret_1d: float, ret_5d: float, ret_20d: float) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        name=symbol,
        themes=[],
        last_close=100,
        ret_1d=ret_1d,
        ret_5d=ret_5d,
        ret_20d=ret_20d,
        amount_ma5=100,
        amount_ma20=100,
        amount_ratio=1,
        high_proximity_20d=-0.05,
        drawdown_20d=-0.05,
        score=50,
        status="中性",
    )


def test_broad_market_crash_closes_new_position_gate() -> None:
    config = {"market_context_groups": [{"name": "A股宽基环境", "symbols": ["000001.SH", "399001.SZ", "399006.SZ"]}]}
    snapshots = {
        "000001.SH": _snapshot("000001.SH", -0.021, -0.03, -0.02),
        "399001.SZ": _snapshot("399001.SZ", -0.035, -0.05, -0.03),
        "399006.SZ": _snapshot("399006.SZ", -0.031, -0.06, -0.04),
    }
    pulses = build_market_pulses(config, snapshots)

    gate = build_trading_gate(config, snapshots, pulses)

    assert gate.level == "red"
    assert gate.state == "暂停新仓"
    assert gate.max_initial_position_fraction == 0
