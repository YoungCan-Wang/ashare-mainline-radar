from ashare_mainline_radar.golden_pit import build_golden_pit_report
from ashare_mainline_radar.market import compute_symbol_snapshot
from ashare_mainline_radar.models import KlineSeries, ThemeSnapshot, TradingGate


def _pit_series(symbol: str) -> KlineSeries:
    close = [10 + i * 0.08 for i in range(50)]
    close.extend([14.0, 13.8, 13.5, 13.2, 13.0, 12.8, 12.7, 12.75, 12.8, 13.4])
    amount = [100.0] * 59 + [145.0]
    return KlineSeries(
        symbol=symbol,
        timestamp=list(range(60)),
        open=[value * 0.99 for value in close],
        high=[value * 1.02 for value in close],
        low=[value * 0.97 for value in close],
        close=close,
        volume=[1000.0] * 60,
        amount=amount,
    )


def test_golden_pit_requires_mainline_pullback_and_confirmation() -> None:
    series = _pit_series("600000.SH")
    snapshot = compute_symbol_snapshot("600000.SH", series, instrument={"name": "主线核心"}, themes=["AI算力"])
    assert snapshot is not None
    theme = ThemeSnapshot(
        name="AI算力",
        score=92,
        status="主线成立",
        members=10,
        breadth_5d=0.6,
        breadth_20d=0.8,
        avg_ret_5d=0.02,
        avg_ret_20d=0.15,
        amount_heat=1.1,
        catalyst_count=0,
        leaders=[],
    )
    gate = TradingGate("green", "允许寻找买点", 75, 1 / 3, ["环境正常"], ["分批"])

    report = build_golden_pit_report({snapshot.symbol: snapshot}, {snapshot.symbol: series}, [theme], gate)

    assert report.candidates
    assert report.candidates[0].stage == "止跌确认"
    assert report.candidates[0].action == "触发后可列入试错仓"


def test_red_gate_keeps_golden_pit_in_observation() -> None:
    series = _pit_series("600000.SH")
    snapshot = compute_symbol_snapshot("600000.SH", series, instrument={"name": "主线核心"}, themes=["AI算力"])
    assert snapshot is not None
    theme = ThemeSnapshot("AI算力", 92, "主线成立", 10, 0.6, 0.8, 0.02, 0.15, 1.1, 0, [])
    gate = TradingGate("red", "暂停新仓", 25, 0, ["指数大跌"], ["观察"])

    report = build_golden_pit_report({snapshot.symbol: snapshot}, {snapshot.symbol: series}, [theme], gate)

    assert report.candidates[0].action == "只观察，等待确认"
