from datetime import datetime, timezone

from ashare_mainline_radar.models import KlineSeries
from ashare_mainline_radar.strategy_backtest import StrategyTrade, _metrics, sample_breadth_symbols


def _trade(portfolio_return: float) -> StrategyTrade:
    return StrategyTrade(
        symbol="000001.SZ",
        name="测试股票",
        theme="测试主题",
        signal_date="2026-01-01",
        entry_date="2026-01-02",
        exit_date="2026-01-20",
        entry_price=10,
        exit_price=11,
        gross_return=0.10,
        net_return=0.097,
        portfolio_return=portfolio_return,
        position_fraction=1 / 3,
        exit_reason="固定持有15日",
    )


def test_metrics_use_portfolio_sizing_not_full_notional_return() -> None:
    metrics = _metrics([_trade(0.03), _trade(-0.02)])

    assert metrics.trades == 2
    assert metrics.avg_return is not None
    assert round(metrics.avg_return, 4) == 0.005
    assert metrics.cumulative_return is not None
    assert round(metrics.cumulative_return, 4) == 0.0094
    assert metrics.max_drawdown is not None
    assert round(metrics.max_drawdown, 4) == -0.02


def test_breadth_sample_is_deterministic_and_spans_sorted_universe() -> None:
    symbols = [f"{index:06d}.SZ" for index in range(100)]

    first = sample_breadth_symbols(symbols, 10)
    second = sample_breadth_symbols(list(reversed(symbols)), 10)

    assert first == second
    assert len(first) == 10
    assert first[0] == "000000.SZ"
    assert first[-1] == "000090.SZ"


def test_metrics_value_concurrent_positions_as_one_portfolio() -> None:
    timestamps = [int(datetime(2026, 1, day, tzinfo=timezone.utc).timestamp() * 1000) for day in range(1, 6)]
    trades = [
        StrategyTrade(
            symbol="000001.SZ",
            name="上涨",
            theme="主题一",
            signal_date="2026-01-01",
            entry_date="2026-01-02",
            exit_date="2026-01-05",
            entry_price=10,
            exit_price=11,
            gross_return=0.1,
            net_return=0.1,
            portfolio_return=0.1 / 3,
            position_fraction=1 / 3,
            exit_reason="固定持有",
        ),
        StrategyTrade(
            symbol="000002.SZ",
            name="下跌",
            theme="主题二",
            signal_date="2026-01-01",
            entry_date="2026-01-02",
            exit_date="2026-01-05",
            entry_price=20,
            exit_price=18,
            gross_return=-0.1,
            net_return=-0.1,
            portfolio_return=-0.1 / 3,
            position_fraction=1 / 3,
            exit_reason="固定持有",
        ),
    ]
    klines = {
        "000001.SZ": KlineSeries(
            "000001.SZ", timestamps, [10] * 5, [11] * 5, [9] * 5, [10, 10, 10.5, 11, 11], [1] * 5, [1] * 5
        ),
        "000002.SZ": KlineSeries(
            "000002.SZ", timestamps, [20] * 5, [21] * 5, [18] * 5, [20, 20, 19, 18, 18], [1] * 5, [1] * 5
        ),
    }

    metrics = _metrics(trades, klines)

    assert metrics.cumulative_return is not None
    assert round(metrics.cumulative_return, 8) == 0
