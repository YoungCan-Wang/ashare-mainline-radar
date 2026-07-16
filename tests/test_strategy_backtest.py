from ashare_mainline_radar.strategy_backtest import StrategyTrade, _metrics


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
