from ashare_mainline_radar.market_context import build_market_pulses
from ashare_mainline_radar.models import MarketStructure, SymbolSnapshot
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
    assert gate.reasons[0].startswith("硬熔断：")


def test_confirmed_breakdown_is_primary_red_trigger_even_with_hot_breadth() -> None:
    config = {"market_context_groups": [{"name": "A股宽基环境", "symbols": ["000001.SH", "399001.SZ", "399006.SZ"]}]}
    snapshots = {
        "000001.SH": _snapshot("000001.SH", 0.01, -0.02, -0.08),
        "399001.SZ": _snapshot("399001.SZ", 0.015, -0.01, -0.07),
        "399006.SZ": _snapshot("399006.SZ", 0.012, -0.015, -0.09),
    }
    for index in range(10):
        symbol = f"6000{index:02d}.SH"
        snapshots[symbol] = _snapshot(symbol, 0.02, 0.01, -0.05)
    pulses = build_market_pulses(config, snapshots)
    structure = MarketStructure(
        status="破位确认",
        score=0,
        index_count=3,
        above_ma5_ratio=0.33,
        above_ma20_ratio=0,
        bullish_alignment_ratio=0,
        volume_confirmation_ratio=0,
        higher_high_low_ratio=0,
        confirmed_breakdown_ratio=1,
        evidence=["连续3日跌破20日线指数 100%"],
    )

    gate = build_trading_gate(config, snapshots, pulses, structure)

    assert gate.level == "red"
    assert "硬熔断：指数结构破位确认" in gate.reasons[0]
    assert "连续3日跌破20日线指数 100%" in gate.reasons[0]


def test_positive_stock_breadth_downgrades_index_drop_to_caution() -> None:
    config = {"market_context_groups": [{"name": "A股宽基环境", "symbols": ["000001.SH", "399001.SZ", "399006.SZ"]}]}
    snapshots = {
        "000001.SH": _snapshot("000001.SH", -0.025, -0.03, -0.02),
        "399001.SZ": _snapshot("399001.SZ", -0.028, -0.05, -0.03),
        "399006.SZ": _snapshot("399006.SZ", -0.024, -0.06, -0.04),
    }
    for index in range(10):
        symbol = f"6000{index:02d}.SH"
        snapshots[symbol] = _snapshot(symbol, 0.01 if index < 7 else -0.005, 0.01, 0.02)
    pulses = build_market_pulses(config, snapshots)

    gate = build_trading_gate(config, snapshots, pulses)

    assert gate.level == "orange"
    assert gate.advance_ratio == 0.7
    assert "上涨占比 70.0%" in gate.reasons[-1]


def test_systemic_stock_selloff_closes_gate_even_without_index_crash() -> None:
    config = {"market_context_groups": [{"name": "A股宽基环境", "symbols": ["000001.SH", "399001.SZ", "399006.SZ"]}]}
    snapshots = {
        "000001.SH": _snapshot("000001.SH", -0.008, 0.01, 0.02),
        "399001.SZ": _snapshot("399001.SZ", -0.009, 0.01, 0.02),
        "399006.SZ": _snapshot("399006.SZ", -0.007, 0.01, 0.02),
    }
    for index in range(10):
        symbol = f"6000{index:02d}.SH"
        snapshots[symbol] = _snapshot(symbol, 0.005 if index == 0 else -0.03, -0.04, -0.02)
    pulses = build_market_pulses(config, snapshots)

    gate = build_trading_gate(config, snapshots, pulses)

    assert gate.level == "red"
    assert gate.advance_ratio == 0.1
    assert gate.decline_2pct_ratio == 0.9
