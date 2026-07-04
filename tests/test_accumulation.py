from ashare_mainline_radar.accumulation import build_accumulation_report
from ashare_mainline_radar.market import compute_symbol_snapshot
from ashare_mainline_radar.models import KlineSeries, ThemeSnapshot


def _low_base_with_volume(symbol: str) -> KlineSeries:
    close = [20.0 - i * 0.08 for i in range(35)]
    close.extend([13.8 - i * 0.04 for i in range(15)])
    close.extend([12.9 + i * 0.065 for i in range(30)])
    amount = [100.0 for _ in range(50)]
    amount.extend([115.0 + i * 2.0 for i in range(10)])
    amount.extend([145.0 + i * 3.0 for i in range(20)])
    return KlineSeries(
        symbol=symbol,
        timestamp=[1780000000000 + i * 86400000 for i in range(80)],
        open=[value * 0.995 for value in close],
        high=[value * 1.025 for value in close],
        low=[value * 0.975 for value in close],
        close=close,
        volume=[1000.0 + i for i in range(80)],
        amount=amount,
    )


def _extended_uptrend(symbol: str) -> KlineSeries:
    close = [10.0 + i * 0.16 for i in range(80)]
    return KlineSeries(
        symbol=symbol,
        timestamp=[1780000000000 + i * 86400000 for i in range(80)],
        open=[value * 0.995 for value in close],
        high=[value * 1.02 for value in close],
        low=[value * 0.98 for value in close],
        close=close,
        volume=[1000.0 + i for i in range(80)],
        amount=[100.0 + i * 3.0 for i in range(80)],
    )


def test_build_accumulation_report_finds_low_base_volume_turn() -> None:
    series = _low_base_with_volume("600000.SH")
    snapshot = compute_symbol_snapshot("600000.SH", series, instrument={"name": "测试股票"}, themes=["机器人"])
    assert snapshot is not None
    theme = ThemeSnapshot(
        name="机器人",
        score=82.0,
        status="主线成立",
        members=3,
        breadth_5d=0.66,
        breadth_20d=0.66,
        avg_ret_5d=0.03,
        avg_ret_20d=0.05,
        amount_heat=1.1,
        catalyst_count=0,
        leaders=[],
    )

    report = build_accumulation_report({"600000.SH": snapshot}, {"600000.SH": series}, [theme])

    assert report.candidates
    assert report.candidates[0].symbol == "600000.SH"
    assert report.candidates[0].primary_theme == "机器人"
    assert report.candidates[0].range_position_60d is not None
    assert report.candidates[0].range_position_60d < 0.58
    assert report.candidates[0].amount_ratio_5_20 is not None
    assert report.candidates[0].amount_ratio_5_20 > 1.08


def test_build_accumulation_report_excludes_high_position_uptrend() -> None:
    series = _extended_uptrend("000001.SZ")
    snapshot = compute_symbol_snapshot("000001.SZ", series, instrument={"name": "高位股票"}, themes=["AI算力"])
    assert snapshot is not None

    report = build_accumulation_report({"000001.SZ": snapshot}, {"000001.SZ": series}, [])

    assert report.candidates == []
