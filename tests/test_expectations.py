from datetime import datetime, timedelta, timezone

from ashare_mainline_radar.expectations import build_expectation_gap_report
from ashare_mainline_radar.models import FundamentalReport, FundamentalSnapshot, KlineSeries, SymbolSnapshot


def _series(symbol: str) -> KlineSeries:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = [int((start + timedelta(days=i)).timestamp() * 1000) for i in range(40)]
    closes = [100.0] * 30 + [96.0, 95.0, 94.0] + [94.0] * 7
    amounts = [100.0] * 30 + [180.0, 170.0, 160.0] + [100.0] * 7
    return KlineSeries(
        symbol=symbol,
        timestamp=timestamps,
        open=closes,
        high=[value * 1.01 for value in closes],
        low=[value * 0.99 for value in closes],
        close=closes,
        volume=[1000.0] * 40,
        amount=amounts,
    )


def test_strong_results_with_volume_selloff_flag_expectation_risk() -> None:
    symbol = "600000.SH"
    fundamental = FundamentalSnapshot(
        symbol=symbol,
        period_end="2026-03-31",
        announce_date="2026-01-31",
        revenue_yoy=30,
        net_income_yoy=50,
        roe=12,
        ocfps=1,
        bps=10,
        price_to_book=10,
        revenue_yoy_change=5,
        net_income_yoy_change=10,
        score=82,
        status="基本面兑现",
    )
    snapshot = SymbolSnapshot(symbol, "测试公司", [], 94, -0.01, -0.03, 0.1, 100, 100, 1, -0.1, -0.1, 60, "中性")

    report = build_expectation_gap_report(
        FundamentalReport([fundamental], 1, 1),
        {symbol: _series(symbol)},
        {symbol: snapshot},
    )

    assert report.signals
    assert report.signals[0].status == "利好兑现风险"
