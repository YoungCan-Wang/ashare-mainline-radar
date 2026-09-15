from datetime import datetime, timedelta, timezone

from ashare_mainline_radar.models import KlineSeries
from ashare_mainline_radar.volume_lag_backtest import (
    HorizonMetrics,
    VolumeLagRules,
    decide_collection_verdict,
    features_at,
    run_volume_lag_backtest,
)


def _timestamps(count: int) -> list[int]:
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    return [int((start + timedelta(days=index)).timestamp() * 1000) for index in range(count)]


def _series(
    symbol: str,
    close: list[float],
    amount: list[float],
    *,
    open_: list[float] | None = None,
    high: list[float] | None = None,
    low: list[float] | None = None,
) -> KlineSeries:
    return KlineSeries(
        symbol=symbol,
        timestamp=_timestamps(len(close)),
        open=open_ or [value * 0.998 for value in close],
        high=high or [value * 1.01 for value in close],
        low=low or [value * 0.99 for value in close],
        close=close,
        volume=[1000.0] * len(close),
        amount=amount,
    )


def _low_base_volume_lag(symbol: str) -> KlineSeries:
    close = [20.0 - index * 0.12 for index in range(50)]
    close.extend([13.2] * 8)
    close.extend([13.8, 13.7, 13.6])
    close.extend([13.28, 13.30, 13.29, 13.31, 13.30, 13.32, 13.33, 13.34, 13.35])
    close.extend([13.36, 13.37, 13.38, 13.39, 13.40, 13.41])
    amount = [80.0] * 70
    amount.extend([220.0] * 6)
    return _series(symbol, close, amount)


def _high_base_volume_lag(symbol: str) -> KlineSeries:
    close = [10.0 + index * 0.12 for index in range(70)]
    close.extend([close[-1] * 1.004] * 6)
    amount = [80.0] * 70
    amount.extend([240.0] * 6)
    return _series(symbol, close, amount)


def _quiet(symbol: str, last: float = 10.0) -> KlineSeries:
    close = [last + (index % 7) * 0.04 for index in range(76)]
    return _series(symbol, close, [50.0] * 76)


def test_features_flag_limit_up_and_one_price() -> None:
    close = [10.0] * 70
    close.append(11.0)
    amount = [80.0] * 70 + [200.0]
    limit = _series(
        "600000.SH",
        close,
        amount,
        open_=[10.0] * 70 + [10.2],
        high=[10.2] * 70 + [11.0],
        low=[9.8] * 70 + [10.2],
    )
    one_price_close = [10.0] * 70 + [11.0]
    one_price = _series(
        "000001.SZ",
        one_price_close,
        amount,
        open_=[10.0] * 70 + [11.0],
        high=[10.0] * 70 + [11.0],
        low=[10.0] * 70 + [11.0],
    )

    limit_feature = features_at(limit, 70, "600000.SH", "测试股份")
    one_price_feature = features_at(one_price, 70, "000001.SZ", "测试股份")

    assert limit_feature is not None
    assert limit_feature.is_limit_up is True
    assert one_price_feature is not None
    assert one_price_feature.is_one_price is True


def test_backtest_splits_low_base_from_high_base_and_beats_amount_baseline_shape() -> None:
    klines = {
        "600000.SH": _low_base_volume_lag("600000.SH"),
        "600519.SH": _high_base_volume_lag("600519.SH"),
        "000001.SZ": _quiet("000001.SZ", 12.0),
        "000002.SZ": _quiet("000002.SZ", 9.5),
        "000063.SZ": _quiet("000063.SZ", 8.0),
        "002415.SZ": _quiet("002415.SZ", 11.0),
        "300750.SZ": _quiet("300750.SZ", 7.5),
        "601318.SH": _quiet("601318.SH", 13.0),
        "601899.SH": _quiet("601899.SH", 6.5),
        "000858.SZ": _quiet("000858.SZ", 15.0),
    }
    instruments = {
        "600000.SH": {"name": "低位股份"},
        "600519.SH": {"name": "高位股份"},
        "000001.SZ": {"name": "安静一"},
        "000002.SZ": {"name": "安静二"},
        "000063.SZ": {"name": "安静三"},
        "002415.SZ": {"name": "安静四"},
        "300750.SZ": {"name": "安静五"},
        "601318.SH": {"name": "安静六"},
        "601899.SH": {"name": "安静七"},
        "000858.SZ": {"name": "*ST排除"},
    }
    report = run_volume_lag_backtest(klines, instruments, rules=VolumeLagRules(max_per_day=4, warmup_days=60))

    assert report["feeds_next_buy"] is False
    assert report["persist_to_supabase"] is False
    low = report["strategies"]["volume_lag_low_base"]["all"]["next_open"]["1"]
    high = report["strategies"]["high_base_lag"]["all"]["next_open"]["1"]
    assert low["trades"] >= 1
    assert high["trades"] >= 1
    assert "random_same_size" in report["strategies"]
    assert "amount_topn" in report["strategies"]
    assert report["verdict"]["decision"] in {"GO", "NO-GO"}


def test_st_names_are_excluded() -> None:
    klines = {"000858.SZ": _low_base_volume_lag("000858.SZ")}
    report = run_volume_lag_backtest(klines, {"000858.SZ": {"name": "*ST测试"}}, rules=VolumeLagRules())
    assert report["metadata"]["symbols_scanned"] == 0
    assert report["trade_count"] == 0


def test_verdict_requires_positive_sample_out_and_baseline_edge() -> None:
    go = decide_collection_verdict(
        HorizonMetrics(120, 0, 0.55, 0.012, 0.01, -0.04, -0.03),
        HorizonMetrics(200, 0, 0.52, 0.004, 0.003, -0.05, -0.04),
        HorizonMetrics(200, 0, 0.48, 0.001, 0.0, -0.06, -0.05),
        HorizonMetrics(200, 0, 0.49, 0.0005, 0.0, -0.06, -0.05),
        min_trades=80,
        min_mean_net=0.001,
    )
    no_go = decide_collection_verdict(
        HorizonMetrics(20, 0, 0.6, 0.02, 0.01, -0.02, -0.02),
        HorizonMetrics(90, 0, 0.45, -0.004, -0.003, -0.08, -0.06),
        HorizonMetrics(90, 0, 0.5, 0.001, 0.0, -0.05, -0.04),
        HorizonMetrics(90, 0, 0.5, 0.0, 0.0, -0.05, -0.04),
        min_trades=80,
        min_mean_net=0.001,
    )
    assert go["decision"] == "GO"
    assert go["collect_into_daily"] is True
    assert no_go["decision"] == "NO-GO"
    assert no_go["collect_into_daily"] is False
