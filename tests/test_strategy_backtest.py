from datetime import datetime, timezone

from ashare_mainline_radar.models import KlineSeries
from ashare_mainline_radar.strategy_backtest import (
    BacktestMetrics,
    StrategyTrade,
    _exposure_matched_benchmark_return,
    _group_diagnostics,
    _metrics,
    _selection_score,
    sample_breadth_symbols,
)


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


def test_walk_forward_selection_rejects_tiny_samples() -> None:
    tiny = BacktestMetrics(11, 1.0, 0.1, 0.1, 0.5, -0.01, 2.0, "2026-01-01", "2026-02-01")
    eligible = BacktestMetrics(12, 0.5, 0.01, 0.01, 0.08, -0.04, 1.2, "2026-01-01", "2026-02-01")

    assert _selection_score(tiny) == float("-inf")
    assert _selection_score(eligible) == 2.0


def test_diagnostics_separate_exit_and_market_gate_contributions() -> None:
    winning = _trade(0.03)
    winning.net_return = 0.09
    winning.market_gate = "yellow"
    losing = _trade(-0.02)
    losing.net_return = -0.06
    losing.exit_reason = "收盘跌破8%失效位，次日开盘退出"
    losing.market_gate = "green"

    exits = _group_diagnostics([winning, losing], "exit")
    gates = _group_diagnostics([winning, losing], "gate")

    assert {item.group for item in exits} == {"固定持有15日", "收盘跌破8%失效位，次日开盘退出"}
    assert {item.group for item in gates} == {"市场闸门：yellow", "市场闸门：green"}


def test_exposure_matched_benchmark_uses_strategy_position_size() -> None:
    timestamps = [int(datetime(2026, 1, day, tzinfo=timezone.utc).timestamp() * 1000) for day in range(1, 6)]
    benchmark = KlineSeries(
        "510300.SH",
        timestamps,
        [10, 10, 10.2, 10.6, 11],
        [10.2, 10.2, 10.4, 10.8, 11.2],
        [9.9, 9.9, 10.1, 10.5, 10.9],
        [10, 10, 10.2, 10.6, 11],
        [1] * 5,
        [1] * 5,
    )
    trade = _trade(0.0)
    trade.entry_date = "2026-01-02"
    trade.exit_date = "2026-01-05"
    trade.position_fraction = 0.1

    matched = _exposure_matched_benchmark_return([trade], benchmark)

    assert matched is not None
    assert 0 < matched < 0.1
