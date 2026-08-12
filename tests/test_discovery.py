from ashare_mainline_radar.discovery import build_unmapped_strength_report
from ashare_mainline_radar.models import SymbolSnapshot


def _snapshot(symbol: str, themes: list[str], percentile: float = 95) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        name="测试公司",
        themes=themes,
        last_close=10,
        ret_1d=0.01,
        ret_5d=0.04,
        ret_20d=0.12,
        amount_ma5=120,
        amount_ma20=100,
        amount_ratio=1.2,
        high_proximity_20d=-0.02,
        drawdown_20d=-0.02,
        score=90,
        status="突破观察",
        relative_percentile=percentile,
    )


def test_unmapped_strength_excludes_mapped_stocks_and_funds() -> None:
    snapshots = {
        "000001.SZ": _snapshot("000001.SZ", []),
        "000002.SZ": _snapshot("000002.SZ", ["机器人"]),
        "159001.SZ": _snapshot("159001.SZ", []),
    }
    instruments = {
        "000001.SZ": {"name": "测试公司"},
        "000002.SZ": {"name": "主题公司"},
        "159001.SZ": {"name": "测试ETF"},
    }

    report = build_unmapped_strength_report(snapshots, instruments, "universe")

    assert [item.symbol for item in report.candidates] == ["000001.SZ"]
    assert report.scanned_unmapped == 1
