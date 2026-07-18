from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from statistics import fmean, median
from typing import Any

from .config import configured_symbols, theme_candidate_symbols, theme_symbol_map
from .cross_market import build_cross_market_report
from .execution import (
    TradingCostModel,
    apply_execution_costs,
    build_trade_execution_plan,
    entry_confirmed,
    is_fund_security,
    is_sealed_limit_down,
    is_sealed_limit_up,
)
from .market import build_theme_snapshots, compute_symbol_snapshot
from .market_context import build_market_pulses
from .market_structure import build_market_structure
from .models import KlineSeries, SymbolSnapshot, cn_market_date_from_ms
from .risk_gate import build_trading_gate
from .strategy_rules import SIGNAL_PROFILES


@dataclass
class StrategyTrade:
    symbol: str
    name: str
    theme: str
    signal_date: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    gross_return: float
    net_return: float
    portfolio_return: float
    position_fraction: float
    exit_reason: str
    cross_market_status: str | None = None
    trigger_date: str | None = None
    raw_entry_price: float | None = None
    raw_exit_price: float | None = None
    buy_fee_rate: float = 0.0
    sell_fee_rate: float = 0.0
    fee_breakdown: dict[str, Any] = field(default_factory=dict)
    exit_delay_days: int = 0
    market_gate: str | None = None
    signal_status: str | None = None
    signal_score: float | None = None
    signal_ret_5d: float | None = None
    signal_ret_20d: float | None = None
    signal_amount_ratio: float | None = None
    signal_high_proximity_20d: float | None = None
    theme_vehicle_symbol: str | None = None
    theme_vehicle_net_return: float | None = None
    stock_selection_excess: float | None = None
    signal_symbol: str | None = None
    signal_name: str | None = None


@dataclass
class SimulationStats:
    plans_created: int = 0
    plans_expired: int = 0
    entries_blocked_limit_up: int = 0
    entries_blocked_suspension: int = 0
    entries_blocked_no_theme_vehicle: int = 0
    exits_delayed_limit_down: int = 0
    exits_delayed_suspension: int = 0


@dataclass
class BacktestMetrics:
    trades: int
    win_rate: float | None
    avg_return: float | None
    median_return: float | None
    cumulative_return: float | None
    max_drawdown: float | None
    profit_factor: float | None
    start_date: str | None
    end_date: str | None


@dataclass
class BacktestVariant:
    name: str
    hold_days: int
    max_positions: int
    cross_market_mode: str
    signal_mode: str
    signal_profile: str
    position_fraction: float
    stop_loss: float
    all_period: BacktestMetrics
    train: BacktestMetrics
    validation: BacktestMetrics
    test: BacktestMetrics
    trades: list[StrategyTrade] = field(default_factory=list)
    execution_stats: SimulationStats = field(default_factory=SimulationStats)
    theme_exit_days: int | None = 2


@dataclass
class FoldResult:
    name: str
    start_date: str
    end_date: str
    metrics: BacktestMetrics
    benchmark_return: float | None
    exposure_matched_benchmark_return: float | None
    benchmark_drawdown: float | None
    excess_return: float | None


@dataclass
class WalkForwardStep:
    name: str
    training_end: str
    test_start: str
    test_end: str
    selected_variant: str
    selection_score: float
    metrics: BacktestMetrics
    benchmark_return: float | None
    exposure_matched_benchmark_return: float | None
    excess_return: float | None


@dataclass
class WalkForwardAudit:
    steps: list[WalkForwardStep]
    positive_steps: int
    excess_positive_steps: int
    aggregate_metrics: BacktestMetrics
    verdict: str


@dataclass
class GroupDiagnostic:
    group: str
    trades: int
    win_rate: float | None
    avg_net_return: float | None
    portfolio_contribution: float


@dataclass
class SelectionAttribution:
    period: str
    stock_trades: int
    matched_trades: int
    avg_stock_net_return: float | None
    avg_theme_vehicle_net_return: float | None
    avg_stock_selection_excess: float | None
    portfolio_selection_contribution: float | None


@dataclass
class RobustnessAudit:
    default_variant: str
    positive_folds: int
    excess_positive_folds: int
    total_folds: int
    folds: list[FoldResult]
    doubled_cost_metrics: BacktestMetrics
    exposure_matched_benchmark_return: float | None
    top_five_profit_share: float | None
    theme_trade_counts: dict[str, int]
    etf_proxy_variant: str
    etf_proxy_positive_folds: int
    etf_proxy_excess_positive_folds: int
    etf_proxy_folds: list[FoldResult]
    signal_vehicle_variant: str
    signal_vehicle_positive_folds: int
    signal_vehicle_excess_positive_folds: int
    signal_vehicle_folds: list[FoldResult]
    signal_vehicle_stable_holds: int
    signal_vehicle_total_holds: int
    signal_vehicle_verdict: str
    stock_exit_policy_stable: int
    signal_vehicle_exit_policy_stable: int
    exit_policy_variants_per_mode: int
    exit_policy_verdict: str
    positive_position_capacities: int
    total_position_capacities: int
    positive_signal_profiles: int
    total_signal_profiles: int
    positive_position_sizes: int
    total_position_sizes: int
    positive_stop_losses: int
    total_stop_losses: int
    walk_forward: WalkForwardAudit
    exit_diagnostics: list[GroupDiagnostic]
    gate_diagnostics: list[GroupDiagnostic]
    selection_attribution: list[SelectionAttribution]
    verdict: str


@dataclass
class StrategyBacktestReport:
    generated_for: str
    transaction_cost: float
    stop_loss: float
    position_fraction: float
    warmup_days: int
    breadth_symbols: int
    split_dates: dict[str, str]
    benchmark_returns: dict[str, float | None]
    benchmark_drawdowns: dict[str, float | None]
    variants: list[BacktestVariant]
    robustness: RobustnessAudit
    verdict: str
    cross_market_verdict: str
    cost_model: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def render_strategy_backtest(report: StrategyBacktestReport) -> str:
    lines = [
        "# 主线策略滚动样本外回测",
        "",
        f"- 结论：**{report.verdict}**",
        f"- A/H增量：**{report.cross_market_verdict}**",
        f"- 当前费率下估算单次完整交易成本：{_percent(report.transaction_cost)}",
        f"- 计划单仓上限：{_percent(report.position_fraction)}；回测首笔按计划仓位1/3，不假设后续加仓",
        f"- 硬失效位：{_percent(report.stop_loss)}",
        f"- 历史市场广度样本：{report.breadth_symbols}只",
        f"- 时间切分：训练截至 {report.split_dates['train_end']}，验证截至 {report.split_dates['validation_end']}，最终留出截至 {report.split_dates['test_end']}",
        "",
        "## 成交成本与可成交性",
        "",
        f"- 假设账户资金：{float(report.cost_model.get('account_capital') or 0):,.0f} 元",
        f"- 券商净佣金：{_percent(report.cost_model.get('broker_commission_rate'))} 双边，单笔最低 "
        f"{float(report.cost_model.get('minimum_commission') or 0):.0f} 元",
        f"- 证管费：{_percent(report.cost_model.get('regulatory_fee_rate'))} 双边",
        "- A股经手费：2023-08-28起0.00341%双边，此前0.00487%双边",
        "- A股过户费：2022-04-29起0.001%双边，此前0.002%双边",
        "- 印花税：仅卖出收取，2023-08-28起0.05%，此前0.10%",
        f"- 滑点：{_percent(report.cost_model.get('slippage_rate_each_side'))} 每边",
        "- 封死涨停不成交并取消该计划；停牌同样不成交。封死跌停或停牌无法卖出时，顺延到首个可成交交易日。",
        "",
        "## 基准",
        "",
        "| 区间 | 沪深300ETF收益 | 沪深300ETF最大回撤 |",
        "| --- | ---: | ---: |",
    ]
    for name, label in (("all", "全期"), ("train", "训练"), ("validation", "验证"), ("test", "最终留出")):
        lines.append(
            f"| {label} | {_percent(report.benchmark_returns.get(name))} | "
            f"{_percent(report.benchmark_drawdowns.get(name))} |"
        )
    lines.extend(
        [
            "",
            "## 参数稳定性",
            "",
            "| 方案 | 全期交易 | 全期收益 | 全期回撤 | 验证交易 | 验证均值 | 验证收益 | 留出交易 | 留出均值 | 留出收益 | 留出回撤 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for variant in report.variants:
        lines.append(
            f"| {variant.name} | {variant.all_period.trades} | {_percent(variant.all_period.cumulative_return)} | "
            f"{_percent(variant.all_period.max_drawdown)} | {variant.validation.trades} | "
            f"{_percent(variant.validation.avg_return)} | {_percent(variant.validation.cumulative_return)} | "
            f"{variant.test.trades} | {_percent(variant.test.avg_return)} | "
            f"{_percent(variant.test.cumulative_return)} | {_percent(variant.test.max_drawdown)} |"
        )
    core = next((item for item in report.variants if item.name == report.robustness.default_variant), None)
    if core:
        stats = core.execution_stats
        lines.extend(
            [
                "",
                "## 核心方案执行统计",
                "",
                f"- 生成交易计划：{stats.plans_created} 个；等待期满未触发：{stats.plans_expired} 个",
                f"- 封死涨停无法买入：{stats.entries_blocked_limit_up} 次；停牌无法买入：{stats.entries_blocked_suspension} 次",
                f"- 个股信号主题缺少可交易ETF：{stats.entries_blocked_no_theme_vehicle} 次",
                f"- 封死跌停导致延迟退出：{stats.exits_delayed_limit_down} 个交易日；停牌导致延迟退出：{stats.exits_delayed_suspension} 个交易日",
            ]
        )
    lines.extend(
        [
            "",
            "## 反过拟合审计",
            "",
            f"- 核心方案：`{report.robustness.default_variant}`",
            f"- 时间折为正：{report.robustness.positive_folds}/{report.robustness.total_folds}",
            f"- 跑赢沪深300ETF的时间折：{report.robustness.excess_positive_folds}/{report.robustness.total_folds}",
            f"- 双倍成本全期收益：{_percent(report.robustness.doubled_cost_metrics.cumulative_return)}",
            f"- 全期同暴露沪深300ETF：{_percent(report.robustness.exposure_matched_benchmark_return)}；"
            f"核心超额 {_percent((core.all_period.cumulative_return or 0) - (report.robustness.exposure_matched_benchmark_return or 0)) if core else 'n/a'}",
            f"- 前五笔盈利占全部正收益：{_percent(report.robustness.top_five_profit_share)}",
            f"- ETF代理方案：`{report.robustness.etf_proxy_variant}`，时间折为正 "
            f"{report.robustness.etf_proxy_positive_folds}/{len(report.robustness.etf_proxy_folds)}，跑赢基准 "
            f"{report.robustness.etf_proxy_excess_positive_folds}/{len(report.robustness.etf_proxy_folds)}",
            f"- 个股先行信号+主题ETF执行：`{report.robustness.signal_vehicle_variant}`，时间折为正 "
            f"{report.robustness.signal_vehicle_positive_folds}/{len(report.robustness.signal_vehicle_folds)}，跑赢基准 "
            f"{report.robustness.signal_vehicle_excess_positive_folds}/{len(report.robustness.signal_vehicle_folds)}；"
            f"持有期稳定 {report.robustness.signal_vehicle_stable_holds}/"
            f"{report.robustness.signal_vehicle_total_holds}",
            f"- ETF执行挑战者结论：**{report.robustness.signal_vehicle_verdict}**",
            f"- 主题退出敏感性：股票执行 {report.robustness.stock_exit_policy_stable}/"
            f"{report.robustness.exit_policy_variants_per_mode}、ETF执行 "
            f"{report.robustness.signal_vehicle_exit_policy_stable}/"
            f"{report.robustness.exit_policy_variants_per_mode} 档在验证与留出均为正",
            f"- 退出状态机结论：**{report.robustness.exit_policy_verdict}**",
            f"- 仓位容量稳定性：{report.robustness.positive_position_capacities}/"
            f"{report.robustness.total_position_capacities} 档在验证段和留出段均为正",
            f"- 入场强度稳定性：{report.robustness.positive_signal_profiles}/"
            f"{report.robustness.total_signal_profiles} 档在验证段和留出段均为正",
            f"- 单仓风险预算稳定性：{report.robustness.positive_position_sizes}/"
            f"{report.robustness.total_position_sizes} 档在验证段和留出段均为正",
            f"- 止损敏感性：{report.robustness.positive_stop_losses}/"
            f"{report.robustness.total_stop_losses} 档在验证段和留出段均为正",
            f"- 滚动参数选择：{report.robustness.walk_forward.positive_steps}/"
            f"{len(report.robustness.walk_forward.steps)} 段为正，跑赢基准 "
            f"{report.robustness.walk_forward.excess_positive_steps}/{len(report.robustness.walk_forward.steps)} 段；"
            f"合并收益 {_percent(report.robustness.walk_forward.aggregate_metrics.cumulative_return)}",
            f"- 滚动选择结论：**{report.robustness.walk_forward.verdict}**",
            f"- 审计结论：**{report.robustness.verdict}**",
            "",
            "| 方案 | 时间折 | 起始 | 结束 | 交易数 | 收益 | 回撤 | 满仓沪深300ETF | 同暴露基准 | 基准回撤 | 超额 |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for variant_name, folds in (
        (report.robustness.default_variant, report.robustness.folds),
        (report.robustness.etf_proxy_variant, report.robustness.etf_proxy_folds),
        (report.robustness.signal_vehicle_variant, report.robustness.signal_vehicle_folds),
    ):
        for fold in folds:
            lines.append(
                f"| {variant_name} | {fold.name} | {fold.start_date} | {fold.end_date} | "
                f"{fold.metrics.trades} | {_percent(fold.metrics.cumulative_return)} | "
                f"{_percent(fold.metrics.max_drawdown)} | {_percent(fold.benchmark_return)} | "
                f"{_percent(fold.exposure_matched_benchmark_return)} | {_percent(fold.benchmark_drawdown)} | "
                f"{_percent(fold.excess_return)} |"
            )
    lines.extend(
        [
            "",
            "## 滚动参数选择",
            "",
            "每一步只用此前区间选择方案，再评估紧随其后的时间折；选择范围预先固定为1/2/3仓、10/15/20日和A/H关闭/确认。",
            "",
            "| 步骤 | 训练截至 | 测试区间 | 过去数据选中方案 | 测试交易 | 测试收益 | 满仓基准 | 同暴露基准 | 超额 |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for step in report.robustness.walk_forward.steps:
        lines.append(
            f"| {step.name} | {step.training_end} | {step.test_start} 至 {step.test_end} | "
            f"`{step.selected_variant}` | {step.metrics.trades} | {_percent(step.metrics.cumulative_return)} | "
            f"{_percent(step.benchmark_return)} | {_percent(step.exposure_matched_benchmark_return)} | "
            f"{_percent(step.excess_return)} |"
        )
    lines.extend(
        [
            "",
            "## 亏损来源诊断",
            "",
            "| 分组 | 交易数 | 胜率 | 单笔扣费净收益均值 | 组合贡献简单合计 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in [*report.robustness.exit_diagnostics, *report.robustness.gate_diagnostics]:
        lines.append(
            f"| {item.group} | {item.trades} | {_percent(item.win_rate)} | "
            f"{_percent(item.avg_net_return)} | {_percent(item.portfolio_contribution)} |"
        )
    lines.extend(
        [
            "",
            "## 主线时机与主线内选股归因",
            "",
            "将每笔个股交易按完全相同的进出日期和仓位映射到该主题首个有完整行情的ETF；"
            "该对照不改变交易，只判断收益来自主线时机还是个股选择。",
            "",
            "| 区间 | 个股交易 | ETF可比交易 | 个股单笔净收益 | 主题ETF单笔净收益 | 个股选择超额 | 组合选股贡献 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in report.robustness.selection_attribution:
        lines.append(
            f"| {item.period} | {item.stock_trades} | {item.matched_trades} | "
            f"{_percent(item.avg_stock_net_return)} | {_percent(item.avg_theme_vehicle_net_return)} | "
            f"{_percent(item.avg_stock_selection_excess)} | "
            f"{_percent(item.portfolio_selection_contribution)} |"
        )
    lines.extend(["", "## 审计说明", ""])
    lines.extend(f"- {note}" for note in report.notes)
    lines.append("")
    return "\n".join(lines)


def _slice_series(series: KlineSeries, cutoff: int, lookback: int = 220) -> KlineSeries | None:
    end = bisect_right(series.timestamp, cutoff)
    start = max(0, end - lookback)
    if end - start < 61:
        return None
    return KlineSeries(
        symbol=series.symbol,
        timestamp=series.timestamp[start:end],
        open=series.open[start:end],
        high=series.high[start:end],
        low=series.low[start:end],
        close=series.close[start:end],
        volume=series.volume[start:end],
        amount=series.amount[start:end],
    )


def _market_slice(klines: dict[str, KlineSeries], cutoff: int) -> dict[str, KlineSeries]:
    result: dict[str, KlineSeries] = {}
    for symbol, series in klines.items():
        sliced = _slice_series(series, cutoff)
        if sliced and sliced.usable:
            result[symbol] = sliced
    return result


def _snapshots(
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    symbol_to_themes: dict[str, list[str]],
) -> dict[str, SymbolSnapshot]:
    result: dict[str, SymbolSnapshot] = {}
    for symbol, series in klines.items():
        snapshot = compute_symbol_snapshot(symbol, series, instruments.get(symbol), symbol_to_themes.get(symbol, []))
        if snapshot:
            result[symbol] = snapshot
    return result


def _price_on_or_before(series: KlineSeries, timestamp: int, field: str) -> float | None:
    index = bisect_right(series.timestamp, timestamp) - 1
    if index < 0:
        return None
    values = getattr(series, field)
    return values[index] if index < len(values) else None


def _portfolio_performance(
    trades: list[StrategyTrade],
    klines: dict[str, KlineSeries],
) -> tuple[float | None, float | None]:
    if not trades:
        return None, None
    calendar = _calendar(klines)
    dated_calendar = [(cn_market_date_from_ms(timestamp) or "", timestamp) for timestamp in calendar]
    start_date = min(trade.entry_date for trade in trades)
    end_date = max(trade.exit_date for trade in trades)
    entries: dict[str, list[tuple[int, StrategyTrade]]] = {}
    exits: dict[str, list[tuple[int, StrategyTrade]]] = {}
    for trade_id, trade in enumerate(trades):
        entries.setdefault(trade.entry_date, []).append((trade_id, trade))
        exits.setdefault(trade.exit_date, []).append((trade_id, trade))

    cash = 1.0
    active: dict[int, tuple[StrategyTrade, float, float]] = {}
    peak = 1.0
    max_drawdown = 0.0
    for date, timestamp in dated_calendar:
        if date < start_date or date > end_date:
            continue
        for trade_id, trade in exits.get(date, []):
            position = active.pop(trade_id, None)
            if position is None:
                continue
            _, shares, _ = position
            cash += shares * trade.exit_price * (1 - trade.sell_fee_rate)

        opening_equity = cash
        for trade, shares, _ in active.values():
            series = klines.get(trade.symbol)
            price = _price_on_or_before(series, timestamp, "open") if series else None
            if price is not None:
                opening_equity += shares * price
        for trade_id, trade in entries.get(date, []):
            target_notional = opening_equity * trade.position_fraction
            notional = min(cash / (1 + trade.buy_fee_rate), target_notional)
            if notional <= 0:
                continue
            cash -= notional * (1 + trade.buy_fee_rate)
            active[trade_id] = (trade, notional / trade.entry_price, notional)

        closing_equity = cash
        for trade, shares, _ in active.values():
            series = klines.get(trade.symbol)
            price = _price_on_or_before(series, timestamp, "close") if series else None
            if price is not None:
                closing_equity += shares * price
        peak = max(peak, closing_equity)
        max_drawdown = min(max_drawdown, closing_equity / peak - 1)
    return cash - 1, max_drawdown


def _metrics(
    trades: list[StrategyTrade],
    klines: dict[str, KlineSeries] | None = None,
) -> BacktestMetrics:
    if not trades:
        return BacktestMetrics(0, None, None, None, None, None, None, None, None)
    returns = [trade.portfolio_return for trade in trades]
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
    cumulative_return = equity - 1
    gains = sum(value for value in returns if value > 0)
    losses = -sum(value for value in returns if value < 0)
    if klines:
        portfolio_return, marked_drawdown = _portfolio_performance(trades, klines)
        if portfolio_return is not None:
            cumulative_return = portfolio_return
        if marked_drawdown is not None:
            max_drawdown = marked_drawdown
    return BacktestMetrics(
        trades=len(trades),
        win_rate=sum(value > 0 for value in returns) / len(returns),
        avg_return=fmean(returns),
        median_return=median(returns),
        cumulative_return=cumulative_return,
        max_drawdown=max_drawdown,
        profit_factor=(gains / losses) if losses > 0 else None,
        start_date=trades[0].signal_date,
        end_date=trades[-1].exit_date,
    )


def _metrics_with_cost(
    trades: list[StrategyTrade],
    cost_model: TradingCostModel,
    klines: dict[str, KlineSeries],
    multiplier: float,
) -> BacktestMetrics:
    adjusted: list[StrategyTrade] = []
    for trade in trades:
        raw_entry = trade.raw_entry_price or trade.entry_price
        raw_exit = trade.raw_exit_price or trade.exit_price
        cost = apply_execution_costs(
            raw_entry,
            raw_exit,
            trade.entry_date,
            trade.exit_date,
            cost_model.account_capital * trade.position_fraction,
            is_fund=is_fund_security(trade.name),
            cost_model=cost_model,
            multiplier=multiplier,
        )
        adjusted.append(
            StrategyTrade(
                **{
                    **asdict(trade),
                    "entry_price": cost["entry_price"],
                    "exit_price": cost["exit_price"],
                    "buy_fee_rate": cost["buy_fee_rate"],
                    "sell_fee_rate": cost["sell_fee_rate"],
                    "net_return": cost["net_return"],
                    "portfolio_return": cost["net_return"] * trade.position_fraction,
                    "fee_breakdown": {"buy": cost["buy_fees"], "sell": cost["sell_fees"]},
                }
            )
        )
    return _metrics(adjusted, klines)


def _calendar(klines: dict[str, KlineSeries], preferred: str = "000001.SH") -> list[int]:
    if preferred in klines:
        return klines[preferred].timestamp
    return max(klines.values(), key=lambda series: len(series.timestamp)).timestamp


def sample_breadth_symbols(symbols: list[str], limit: int) -> list[str]:
    stocks = sorted(symbol for symbol in set(symbols) if symbol.endswith((".SH", ".SZ", ".BJ")))
    if limit <= 0 or len(stocks) <= limit:
        return stocks
    step = len(stocks) / limit
    return [stocks[int(index * step)] for index in range(limit)]


def _etf_proxy_config(theme_config: dict[str, Any]) -> dict[str, Any]:
    proxy = deepcopy(theme_config)
    proxy_themes: list[dict[str, Any]] = []
    for theme in proxy.get("themes", []):
        vehicles = [str(symbol) for symbol in theme.get("vehicles", [])]
        if not vehicles:
            continue
        theme["symbols"] = vehicles
        theme["scoring_symbols"] = vehicles
        theme["candidate_symbols"] = vehicles
        theme["vehicles"] = vehicles
        proxy_themes.append(theme)
    proxy["themes"] = proxy_themes
    return proxy


def _candidate(
    theme_config: dict[str, Any],
    themes: list[Any],
    snapshots: dict[str, SymbolSnapshot],
    cross_status: dict[str, str],
    cross_market_mode: str,
    excluded_symbols: set[str] | None = None,
    excluded_themes: set[str] | None = None,
    eligible_themes: set[str] | None = None,
    signal_profile: str = "base",
) -> tuple[SymbolSnapshot, str, str | None] | None:
    excluded_symbols = excluded_symbols or set()
    excluded_themes = excluded_themes or set()
    thresholds = SIGNAL_PROFILES[signal_profile]
    config_by_theme = {str(item["name"]): item for item in theme_config.get("themes", [])}
    for theme in themes[:3]:
        if theme.status not in {"主线成立", "主线候选"}:
            continue
        if theme.name in excluded_themes:
            continue
        if eligible_themes is not None and theme.name not in eligible_themes:
            continue
        status = cross_status.get(theme.name)
        if cross_market_mode == "confirm" and status in {"A股领先", "A港共同走弱"}:
            continue
        if cross_market_mode == "strict" and status is not None and status != "A港共振":
            continue
        ranked: list[SymbolSnapshot] = []
        for symbol in theme_candidate_symbols(config_by_theme.get(theme.name, {})):
            item = snapshots.get(symbol)
            if (
                item
                and item.symbol not in excluded_symbols
                and item.symbol.endswith((".SH", ".SZ", ".BJ"))
                and item.ret_5d is not None
                and thresholds["min_ret_5d"] <= item.ret_5d < 0.15
                and item.ret_20d is not None
                and item.ret_20d > 0.03
                and item.amount_ratio is not None
                and item.amount_ratio >= thresholds["min_amount_ratio"]
                and item.high_proximity_20d is not None
                and item.high_proximity_20d > thresholds["min_high_proximity"]
            ):
                ranked.append(item)
        if ranked:
            ranked.sort(key=lambda item: item.score, reverse=True)
            return ranked[0], theme.name, status
    return None


def _price_at(series: KlineSeries, timestamp: int, field: str) -> float | None:
    index = bisect_right(series.timestamp, timestamp) - 1
    if index < 0 or series.timestamp[index] != timestamp:
        return None
    values = getattr(series, field)
    return values[index] if index < len(values) else None


def _benchmark_return(series: KlineSeries | None, start: int, end: int) -> float | None:
    if series is None:
        return None
    start_price = _price_at(series, start, "close")
    end_price = _price_at(series, end, "close")
    if not start_price or end_price is None:
        return None
    return end_price / start_price - 1


def _series_drawdown(series: KlineSeries | None, start: int, end: int) -> float | None:
    if series is None:
        return None
    peak: float | None = None
    max_drawdown = 0.0
    for timestamp, close in zip(series.timestamp, series.close):
        if timestamp < start or timestamp > end:
            continue
        peak = close if peak is None else max(peak, close)
        if peak > 0:
            max_drawdown = min(max_drawdown, close / peak - 1)
    return max_drawdown if peak is not None else None


def _bar(series: KlineSeries, timestamp: int) -> dict[str, float] | None:
    index = bisect_right(series.timestamp, timestamp) - 1
    if index < 0 or series.timestamp[index] != timestamp:
        return None
    return {
        "open": series.open[index],
        "high": series.high[index],
        "low": series.low[index],
        "close": series.close[index],
        "volume": series.volume[index],
    }


def _find_entry(
    series: KlineSeries,
    calendar: list[int],
    signal_index: int,
    candidate: SymbolSnapshot,
    hold_days: int,
    max_position_fraction: float,
    stop_loss: float,
    enforce_entry_tradeability: bool = True,
) -> tuple[int | None, int | None, str]:
    plan = build_trade_execution_plan(
        candidate.last_close,
        candidate.status,
        hold_days=hold_days,
        max_position_fraction=max_position_fraction,
        stop_loss=stop_loss,
    )
    last_trigger_index = min(signal_index + plan.valid_for_days, len(calendar) - 2)
    for trigger_index in range(signal_index + 1, last_trigger_index + 1):
        trigger_bar = _bar(series, calendar[trigger_index])
        if not trigger_bar or not entry_confirmed(
            plan,
            day_open=trigger_bar["open"],
            day_high=trigger_bar["high"],
            day_low=trigger_bar["low"],
            day_close=trigger_bar["close"],
        ):
            continue
        entry_index = trigger_index + 1
        if not enforce_entry_tradeability:
            return entry_index, trigger_index, "filled"
        entry_bar = _bar(series, calendar[entry_index])
        if not entry_bar or entry_bar["volume"] <= 0:
            return None, last_trigger_index, "suspension"
        previous_bar = _bar(series, calendar[entry_index - 1])
        entry_date = cn_market_date_from_ms(calendar[entry_index]) or ""
        if previous_bar and is_sealed_limit_up(
            candidate.symbol,
            candidate.name,
            entry_date,
            previous_bar["close"],
            day_low=entry_bar["low"],
            day_close=entry_bar["close"],
            volume=entry_bar["volume"],
        ):
            return None, last_trigger_index, "limit_up"
        return entry_index, trigger_index, "filled"
    return None, last_trigger_index, "expired"


def _find_sellable_exit(
    series: KlineSeries,
    calendar: list[int],
    requested_index: int,
    requested_field: str,
    name: str,
) -> tuple[int | None, float | None, int, int]:
    limit_down_delays = 0
    suspension_delays = 0
    for exit_index in range(requested_index, len(calendar)):
        bar = _bar(series, calendar[exit_index])
        if not bar or bar["volume"] <= 0:
            suspension_delays += 1
            continue
        previous_bar = _bar(series, calendar[exit_index - 1]) if exit_index > 0 else None
        exit_date = cn_market_date_from_ms(calendar[exit_index]) or ""
        if previous_bar and is_sealed_limit_down(
            series.symbol,
            name,
            exit_date,
            previous_bar["close"],
            day_high=bar["high"],
            day_close=bar["close"],
            volume=bar["volume"],
        ):
            limit_down_delays += 1
            continue
        field = requested_field if exit_index == requested_index else "open"
        return exit_index, bar[field], limit_down_delays, suspension_delays
    return None, None, limit_down_delays, suspension_delays


def _theme_vehicle_comparison(
    theme: dict[str, Any] | None,
    klines: dict[str, KlineSeries],
    entry_timestamp: int,
    exit_timestamp: int,
    exit_field: str,
    entry_date: str,
    exit_date: str,
    position_fraction: float,
    cost_model: TradingCostModel,
) -> tuple[str | None, float | None]:
    if theme is None:
        return None, None
    for symbol in theme.get("vehicles", []):
        series = klines.get(str(symbol))
        if series is None:
            continue
        raw_entry_price = _price_at(series, entry_timestamp, "open")
        raw_exit_price = _price_at(series, exit_timestamp, exit_field)
        if not raw_entry_price or not raw_exit_price:
            continue
        cost = apply_execution_costs(
            raw_entry_price,
            raw_exit_price,
            entry_date,
            exit_date,
            cost_model.account_capital * position_fraction,
            is_fund=True,
            cost_model=cost_model,
        )
        return str(symbol), float(cost["net_return"])
    return None, None


def _theme_vehicle_execution(
    theme: dict[str, Any] | None,
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    entry_timestamp: int,
) -> tuple[str, str, KlineSeries] | None:
    if theme is None:
        return None
    for raw_symbol in theme.get("vehicles", []):
        symbol = str(raw_symbol)
        series = klines.get(symbol)
        bar = _bar(series, entry_timestamp) if series is not None else None
        if series is None or bar is None or bar["volume"] <= 0:
            continue
        instrument = instruments.get(symbol) or {}
        name = str(instrument.get("name") or instrument.get("display_name") or f"{symbol} ETF")
        return symbol, name, series
    return None


def simulate_variant(
    theme_config: dict[str, Any],
    a_klines: dict[str, KlineSeries],
    a_instruments: dict[str, dict[str, Any]],
    hk_klines: dict[str, KlineSeries],
    hk_instruments: dict[str, dict[str, Any]],
    hold_days: int,
    cross_market_mode: str,
    signal_mode: str,
    cost_model: TradingCostModel,
    stop_loss: float,
    position_fraction: float,
    max_positions: int,
    signal_profile: str,
    warmup_days: int,
    gate_cache: dict[int, str],
    breadth_symbols: set[str],
    theme_cache: dict[tuple[str, int], set[str]],
    theme_exit_days: int | None = 2,
) -> tuple[list[StrategyTrade], SimulationStats]:
    strategy_config = _etf_proxy_config(theme_config) if signal_mode == "etf_proxy" else theme_config
    config_by_theme = {str(item["name"]): item for item in theme_config.get("themes", [])}
    calendar = _calendar(a_klines)
    symbol_to_themes = theme_symbol_map(strategy_config)
    strategy_symbols = set(configured_symbols(strategy_config))
    gate_symbols = set(configured_symbols(theme_config)) | breadth_symbols
    strategy_klines = {symbol: series for symbol, series in a_klines.items() if symbol in strategy_symbols}
    gate_klines = {symbol: series for symbol, series in a_klines.items() if symbol in gate_symbols}

    def gate_level(timestamp: int) -> str:
        cached = gate_cache.get(timestamp)
        if cached is not None:
            return cached
        current = _market_slice(gate_klines, timestamp)
        gate_snapshots = _snapshots(current, a_instruments, theme_symbol_map(theme_config))
        pulses = build_market_pulses(theme_config, gate_snapshots)
        structure = build_market_structure(theme_config, current)
        level = build_trading_gate(theme_config, gate_snapshots, pulses, structure).level
        gate_cache[timestamp] = level
        return level

    def active_themes(timestamp: int) -> set[str]:
        key = (signal_mode, timestamp)
        cached = theme_cache.get(key)
        if cached is not None:
            return cached
        current = _market_slice(strategy_klines, timestamp)
        current_snapshots = _snapshots(current, a_instruments, symbol_to_themes)
        current_themes = build_theme_snapshots(strategy_config, current_snapshots)
        active = {theme.name for theme in current_themes[:3] if theme.status in {"主线成立", "主线候选"}}
        theme_cache[key] = active
        return active

    trades: list[StrategyTrade] = []
    execution_stats = SimulationStats()
    planned_positions: list[tuple[int, str, str, str]] = []
    index = warmup_days
    while index < len(calendar) - hold_days - 1:
        cutoff = calendar[index]
        current_klines = _market_slice(strategy_klines, cutoff)
        snapshots = _snapshots(current_klines, a_instruments, symbol_to_themes)
        themes = build_theme_snapshots(strategy_config, snapshots)
        entry_gate = gate_level(cutoff)
        if entry_gate == "red":
            index += 1
            continue

        hk_current = _market_slice(hk_klines, cutoff)
        cross = build_cross_market_report(strategy_config, hk_current, hk_instruments, themes, snapshots)
        cross_status = {item.theme: item.status for item in cross.themes}
        confirmed_themes = active_themes(cutoff) & active_themes(calendar[index - 1])
        entry_index = index + 1
        planned_positions = [item for item in planned_positions if item[0] > entry_index]
        excluded_symbols = {item[1] for item in planned_positions}
        excluded_themes = {item[2] for item in planned_positions}
        active_execution_symbols = {item[3] for item in planned_positions}
        slots = max(0, max_positions - len(planned_positions))
        for _ in range(slots):
            selected = _candidate(
                strategy_config,
                themes,
                snapshots,
                cross_status,
                cross_market_mode,
                excluded_symbols,
                excluded_themes,
                confirmed_themes,
                signal_profile,
            )
            if selected is None:
                break
            candidate, theme_name, status = selected
            signal_series = a_klines[candidate.symbol]
            execution_stats.plans_created += 1
            resolved_entry_index, trigger_index, entry_status = _find_entry(
                signal_series,
                calendar,
                index,
                candidate,
                hold_days,
                position_fraction,
                stop_loss,
                enforce_entry_tradeability=signal_mode != "stock_signal_theme_vehicle",
            )
            if resolved_entry_index is None:
                if entry_status == "limit_up":
                    execution_stats.entries_blocked_limit_up += 1
                elif entry_status == "suspension":
                    execution_stats.entries_blocked_suspension += 1
                else:
                    execution_stats.plans_expired += 1
                reservation_end = trigger_index if trigger_index is not None else index + 1
                planned_positions.append((reservation_end, candidate.symbol, theme_name, candidate.symbol))
                excluded_symbols.add(candidate.symbol)
                continue
            entry_index = resolved_entry_index
            entry_timestamp = calendar[entry_index]
            execution_symbol = candidate.symbol
            execution_name = candidate.name
            series = signal_series
            if signal_mode == "stock_signal_theme_vehicle":
                vehicle = _theme_vehicle_execution(
                    config_by_theme.get(theme_name),
                    a_klines,
                    a_instruments,
                    entry_timestamp,
                )
                if vehicle is None:
                    execution_stats.entries_blocked_no_theme_vehicle += 1
                    excluded_symbols.add(candidate.symbol)
                    excluded_themes.add(theme_name)
                    continue
                execution_symbol, execution_name, series = vehicle
                if execution_symbol in active_execution_symbols:
                    excluded_symbols.add(candidate.symbol)
                    excluded_themes.add(theme_name)
                    continue
                entry_bar = _bar(series, entry_timestamp)
                previous_bar = _bar(series, calendar[entry_index - 1]) if entry_index > 0 else None
                entry_date = cn_market_date_from_ms(entry_timestamp) or ""
                if entry_bar and previous_bar and is_sealed_limit_up(
                    execution_symbol,
                    execution_name,
                    entry_date,
                    previous_bar["close"],
                    day_low=entry_bar["low"],
                    day_close=entry_bar["close"],
                    volume=entry_bar["volume"],
                ):
                    execution_stats.entries_blocked_limit_up += 1
                    excluded_symbols.add(candidate.symbol)
                    excluded_themes.add(theme_name)
                    continue
            raw_entry_price = _price_at(series, entry_timestamp, "open")
            if not raw_entry_price or raw_entry_price <= 0:
                excluded_symbols.add(candidate.symbol)
                continue
            trade_position_fraction = position_fraction / 3
            if entry_gate != "green":
                trade_position_fraction /= 2
            exit_index = min(entry_index + hold_days, len(calendar) - 1)
            exit_timestamp = calendar[exit_index]
            exit_reason = f"固定持有{hold_days}日"
            exit_field = "close"
            inactive_theme_days = 0
            for check_index in range(entry_index, exit_index):
                check_close = _price_at(series, calendar[check_index], "close")
                if check_close is not None and check_close <= raw_entry_price * (1 - stop_loss):
                    exit_timestamp = calendar[check_index + 1]
                    exit_field = "open"
                    exit_reason = f"收盘跌破{stop_loss * 100:.0f}%失效位，次日开盘退出"
                    exit_index = check_index + 1
                    break
                check_timestamp = calendar[check_index]
                if theme_exit_days is not None:
                    if theme_name in active_themes(check_timestamp):
                        inactive_theme_days = 0
                    else:
                        inactive_theme_days += 1
                    if inactive_theme_days >= theme_exit_days:
                        exit_days_text = "两" if theme_exit_days == 2 else str(theme_exit_days)
                        exit_timestamp = calendar[check_index + 1]
                        exit_field = "open"
                        exit_reason = (
                            f"主线连续{exit_days_text}日退出前三或失去候选身份，次日开盘退出"
                        )
                        exit_index = check_index + 1
                        break
            resolved_exit_index, raw_exit_price, limit_down_delays, suspension_delays = _find_sellable_exit(
                series,
                calendar,
                exit_index,
                exit_field,
                execution_name,
            )
            execution_stats.exits_delayed_limit_down += limit_down_delays
            execution_stats.exits_delayed_suspension += suspension_delays
            if resolved_exit_index is None or raw_exit_price is None:
                excluded_symbols.add(candidate.symbol)
                continue
            if resolved_exit_index != exit_index:
                exit_reason += f"；因跌停或停牌延迟{resolved_exit_index - exit_index}日"
                exit_field = "open"
            exit_index = resolved_exit_index
            exit_timestamp = calendar[exit_index]
            entry_date = cn_market_date_from_ms(entry_timestamp) or ""
            exit_date = cn_market_date_from_ms(exit_timestamp) or ""
            cost = apply_execution_costs(
                raw_entry_price,
                raw_exit_price,
                entry_date,
                exit_date,
                cost_model.account_capital * trade_position_fraction,
                is_fund=(
                    signal_mode == "stock_signal_theme_vehicle" or is_fund_security(execution_name)
                ),
                cost_model=cost_model,
            )
            vehicle_symbol, vehicle_net_return = _theme_vehicle_comparison(
                config_by_theme.get(theme_name),
                a_klines,
                entry_timestamp,
                exit_timestamp,
                exit_field,
                entry_date,
                exit_date,
                trade_position_fraction,
                cost_model,
            )
            stock_selection_excess = (
                float(cost["net_return"]) - vehicle_net_return
                if vehicle_net_return is not None and signal_mode == "stock_basket"
                else None
            )
            trades.append(
                StrategyTrade(
                    symbol=execution_symbol,
                    name=execution_name,
                    theme=theme_name,
                    signal_date=cn_market_date_from_ms(cutoff) or "",
                    entry_date=entry_date,
                    exit_date=exit_date,
                    entry_price=cost["entry_price"],
                    exit_price=cost["exit_price"],
                    gross_return=cost["gross_return"],
                    net_return=cost["net_return"],
                    portfolio_return=cost["net_return"] * trade_position_fraction,
                    position_fraction=trade_position_fraction,
                    exit_reason=exit_reason,
                    cross_market_status=status,
                    trigger_date=cn_market_date_from_ms(calendar[trigger_index]) if trigger_index is not None else None,
                    raw_entry_price=raw_entry_price,
                    raw_exit_price=raw_exit_price,
                    buy_fee_rate=cost["buy_fee_rate"],
                    sell_fee_rate=cost["sell_fee_rate"],
                    fee_breakdown={"buy": cost["buy_fees"], "sell": cost["sell_fees"]},
                    exit_delay_days=limit_down_delays + suspension_delays,
                    market_gate=entry_gate,
                    signal_status=candidate.status,
                    signal_score=candidate.score,
                    signal_ret_5d=candidate.ret_5d,
                    signal_ret_20d=candidate.ret_20d,
                    signal_amount_ratio=candidate.amount_ratio,
                    signal_high_proximity_20d=candidate.high_proximity_20d,
                    theme_vehicle_symbol=vehicle_symbol if signal_mode == "stock_basket" else None,
                    theme_vehicle_net_return=vehicle_net_return if signal_mode == "stock_basket" else None,
                    stock_selection_excess=stock_selection_excess,
                    signal_symbol=candidate.symbol,
                    signal_name=candidate.name,
                )
            )
            planned_positions.append((exit_index, candidate.symbol, theme_name, execution_symbol))
            active_execution_symbols.add(execution_symbol)
            excluded_symbols.add(candidate.symbol)
            excluded_themes.add(theme_name)
        index += 1
    return trades, execution_stats


def _exposure_matched_benchmark_return(
    trades: list[StrategyTrade], benchmark: KlineSeries | None
) -> float | None:
    if benchmark is None or not trades:
        return None
    timestamps = {
        cn_market_date_from_ms(timestamp) or "": timestamp
        for timestamp in benchmark.timestamp
    }
    synthetic: list[StrategyTrade] = []
    for trade in trades:
        entry_timestamp = timestamps.get(trade.entry_date)
        exit_timestamp = timestamps.get(trade.exit_date)
        if entry_timestamp is None or exit_timestamp is None:
            continue
        entry_price = _price_at(benchmark, entry_timestamp, "open")
        exit_field = "close" if trade.exit_reason.startswith("固定持有") else "open"
        exit_price = _price_at(benchmark, exit_timestamp, exit_field)
        if not entry_price or not exit_price:
            continue
        net_return = exit_price / entry_price - 1
        synthetic.append(
            StrategyTrade(
                symbol=benchmark.symbol,
                name="沪深300ETF同暴露基准",
                theme="同暴露基准",
                signal_date=trade.signal_date,
                entry_date=trade.entry_date,
                exit_date=trade.exit_date,
                entry_price=entry_price,
                exit_price=exit_price,
                gross_return=net_return,
                net_return=net_return,
                portfolio_return=net_return * trade.position_fraction,
                position_fraction=trade.position_fraction,
                exit_reason=trade.exit_reason,
            )
        )
    return _metrics(synthetic, {benchmark.symbol: benchmark}).cumulative_return


def _time_folds(
    trades: list[StrategyTrade],
    calendar: list[int],
    benchmark: KlineSeries | None,
    klines: dict[str, KlineSeries],
    warmup_days: int,
    folds: int = 4,
) -> list[FoldResult]:
    usable = calendar[warmup_days:]
    results: list[FoldResult] = []
    for index in range(folds):
        start_index = int(len(usable) * index / folds)
        end_index = int(len(usable) * (index + 1) / folds) - 1
        start_timestamp = usable[start_index]
        end_timestamp = usable[max(start_index, end_index)]
        start_date = cn_market_date_from_ms(start_timestamp) or ""
        end_date = cn_market_date_from_ms(end_timestamp) or ""
        fold_trades = [trade for trade in trades if start_date <= trade.signal_date <= end_date]
        benchmark_return = _benchmark_return(benchmark, start_timestamp, end_timestamp)
        exposure_matched_return = _exposure_matched_benchmark_return(fold_trades, benchmark)
        metrics = _metrics(fold_trades, klines)
        excess_return = (
            metrics.cumulative_return - exposure_matched_return
            if metrics.cumulative_return is not None and exposure_matched_return is not None
            else None
        )
        results.append(
            FoldResult(
                name=f"fold_{index + 1}",
                start_date=start_date,
                end_date=end_date,
                metrics=metrics,
                benchmark_return=benchmark_return,
                exposure_matched_benchmark_return=exposure_matched_return,
                benchmark_drawdown=_series_drawdown(benchmark, start_timestamp, end_timestamp),
                excess_return=excess_return,
            )
        )
    return results


def _fold_ranges(calendar: list[int], warmup_days: int, folds: int = 4) -> list[tuple[str, str]]:
    usable = calendar[warmup_days:]
    ranges: list[tuple[str, str]] = []
    for index in range(folds):
        start_index = int(len(usable) * index / folds)
        end_index = int(len(usable) * (index + 1) / folds) - 1
        start = cn_market_date_from_ms(usable[start_index]) or ""
        end = cn_market_date_from_ms(usable[max(start_index, end_index)]) or ""
        ranges.append((start, end))
    return ranges


def _selection_score(metrics: BacktestMetrics) -> float:
    if metrics.trades < 12 or metrics.cumulative_return is None:
        return float("-inf")
    drawdown = max(abs(metrics.max_drawdown or 0), 0.02)
    return metrics.cumulative_return / drawdown


def _walk_forward_audit(
    variants: list[BacktestVariant],
    calendar: list[int],
    benchmark: KlineSeries | None,
    klines: dict[str, KlineSeries],
    warmup_days: int,
) -> WalkForwardAudit:
    ranges = _fold_ranges(calendar, warmup_days)
    steps: list[WalkForwardStep] = []
    aggregate_trades: list[StrategyTrade] = []
    for index in range(1, len(ranges)):
        test_start, test_end = ranges[index]
        training_end = ranges[index - 1][1]
        scored: list[tuple[float, str, BacktestVariant]] = []
        for variant in variants:
            training_trades = [
                trade
                for trade in variant.trades
                if trade.signal_date >= ranges[0][0] and trade.exit_date <= training_end
            ]
            metrics = _metrics(training_trades, klines)
            scored.append((_selection_score(metrics), variant.name, variant))
        _, _, selected = max(scored, key=lambda item: (item[0], item[1]))
        test_trades = [
            trade
            for trade in selected.trades
            if test_start <= trade.signal_date and trade.exit_date <= test_end
        ]
        metrics = _metrics(test_trades, klines)
        benchmark_return = _benchmark_return(
            benchmark,
            next(timestamp for timestamp in calendar if (cn_market_date_from_ms(timestamp) or "") >= test_start),
            next(timestamp for timestamp in reversed(calendar) if (cn_market_date_from_ms(timestamp) or "") <= test_end),
        )
        exposure_matched_return = _exposure_matched_benchmark_return(test_trades, benchmark)
        excess_return = (
            metrics.cumulative_return - exposure_matched_return
            if metrics.cumulative_return is not None and exposure_matched_return is not None
            else None
        )
        selected_training = [
            trade
            for trade in selected.trades
            if trade.signal_date >= ranges[0][0] and trade.exit_date <= training_end
        ]
        steps.append(
            WalkForwardStep(
                name=f"step_{index}",
                training_end=training_end,
                test_start=test_start,
                test_end=test_end,
                selected_variant=selected.name,
                selection_score=_selection_score(_metrics(selected_training, klines)),
                metrics=metrics,
                benchmark_return=benchmark_return,
                exposure_matched_benchmark_return=exposure_matched_return,
                excess_return=excess_return,
            )
        )
        aggregate_trades.extend(test_trades)
    positive_steps = sum((step.metrics.cumulative_return or 0) > 0 for step in steps)
    excess_positive_steps = sum((step.excess_return or 0) > 0 for step in steps)
    aggregate_metrics = _metrics(aggregate_trades, klines)
    passed = bool(
        positive_steps >= 2
        and excess_positive_steps >= 2
        and (aggregate_metrics.cumulative_return or 0) > 0
        and (aggregate_metrics.max_drawdown or -1) >= -0.15
    )
    return WalkForwardAudit(
        steps=steps,
        positive_steps=positive_steps,
        excess_positive_steps=excess_positive_steps,
        aggregate_metrics=aggregate_metrics,
        verdict="滚动选择通过初步门槛" if passed else "滚动选择未通过，参数选择过程没有稳定优势",
    )


def _group_diagnostics(
    trades: list[StrategyTrade], key: str
) -> list[GroupDiagnostic]:
    grouped: dict[str, list[StrategyTrade]] = {}
    for trade in trades:
        if key == "exit":
            group = trade.exit_reason.split("；", 1)[0]
        else:
            group = f"市场闸门：{trade.market_gate or '未知'}"
        grouped.setdefault(group, []).append(trade)
    diagnostics = []
    for group, rows in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True):
        net_returns = [trade.net_return for trade in rows]
        diagnostics.append(
            GroupDiagnostic(
                group=group,
                trades=len(rows),
                win_rate=sum(value > 0 for value in net_returns) / len(net_returns),
                avg_net_return=fmean(net_returns),
                portfolio_contribution=sum(trade.portfolio_return for trade in rows),
            )
        )
    return diagnostics


def _selection_attribution(
    trades: list[StrategyTrade],
    train_end_date: str,
    validation_end_date: str,
) -> list[SelectionAttribution]:
    periods = (
        ("全期", trades),
        ("训练", [trade for trade in trades if trade.signal_date <= train_end_date]),
        (
            "验证",
            [trade for trade in trades if train_end_date < trade.signal_date <= validation_end_date],
        ),
        ("最终留出", [trade for trade in trades if trade.signal_date > validation_end_date]),
    )
    results: list[SelectionAttribution] = []
    for period, rows in periods:
        matched = [
            trade
            for trade in rows
            if trade.theme_vehicle_net_return is not None and trade.stock_selection_excess is not None
        ]
        results.append(
            SelectionAttribution(
                period=period,
                stock_trades=len(rows),
                matched_trades=len(matched),
                avg_stock_net_return=(fmean(trade.net_return for trade in matched) if matched else None),
                avg_theme_vehicle_net_return=(
                    fmean(float(trade.theme_vehicle_net_return) for trade in matched) if matched else None
                ),
                avg_stock_selection_excess=(
                    fmean(float(trade.stock_selection_excess) for trade in matched) if matched else None
                ),
                portfolio_selection_contribution=(
                    sum(float(trade.stock_selection_excess) * trade.position_fraction for trade in matched)
                    if matched
                    else None
                ),
            )
        )
    return results


def _top_profit_share(trades: list[StrategyTrade]) -> float | None:
    profits = sorted((trade.portfolio_return for trade in trades if trade.portfolio_return > 0), reverse=True)
    total = sum(profits)
    return sum(profits[:5]) / total if total > 0 else None


def run_strategy_backtest(
    theme_config: dict[str, Any],
    a_klines: dict[str, KlineSeries],
    a_instruments: dict[str, dict[str, Any]],
    hk_klines: dict[str, KlineSeries],
    hk_instruments: dict[str, dict[str, Any]],
    stop_loss: float = 0.08,
    position_fraction: float = 0.25,
    warmup_days: int = 140,
    breadth_symbols: set[str] | None = None,
    cost_model: TradingCostModel | None = None,
) -> StrategyBacktestReport:
    breadth_symbols = breadth_symbols or set()
    cost_model = cost_model or TradingCostModel()
    calendar = _calendar(a_klines)
    usable_dates = calendar[warmup_days:]
    train_end = usable_dates[int(len(usable_dates) * 0.60)]
    validation_end = usable_dates[int(len(usable_dates) * 0.80)]
    train_end_date = cn_market_date_from_ms(train_end) or ""
    validation_end_date = cn_market_date_from_ms(validation_end) or ""

    variants: list[BacktestVariant] = []
    gate_cache: dict[int, str] = {}
    theme_cache: dict[tuple[str, int], set[str]] = {}
    for signal_mode in ("stock_basket", "etf_proxy"):
        for max_positions in (1, 2, 3):
            for hold_days in (10, 15, 20):
                modes = ("off", "confirm") if signal_mode == "stock_basket" else ("off",)
                for mode in modes:
                    trades, execution_stats = simulate_variant(
                        theme_config,
                        a_klines,
                        a_instruments,
                        hk_klines,
                        hk_instruments,
                        hold_days,
                        mode,
                        signal_mode,
                        cost_model,
                        stop_loss,
                        position_fraction,
                        max_positions,
                        "base",
                        warmup_days,
                        gate_cache,
                        breadth_symbols,
                        theme_cache,
                    )
                    train = [trade for trade in trades if trade.signal_date <= train_end_date]
                    validation = [
                        trade for trade in trades if train_end_date < trade.signal_date <= validation_end_date
                    ]
                    test = [trade for trade in trades if trade.signal_date > validation_end_date]
                    variants.append(
                        BacktestVariant(
                            name=(f"{signal_mode}_positions_{max_positions}_hold_{hold_days}_{mode}"),
                            hold_days=hold_days,
                            max_positions=max_positions,
                            cross_market_mode=mode,
                            signal_mode=signal_mode,
                            signal_profile="base",
                            position_fraction=position_fraction,
                            stop_loss=stop_loss,
                            all_period=_metrics(trades, a_klines),
                            train=_metrics(train, a_klines),
                            validation=_metrics(validation, a_klines),
                            test=_metrics(test, a_klines),
                            trades=trades,
                            execution_stats=execution_stats,
                        )
                    )

    for hold_days in (10, 15, 20):
        trades, execution_stats = simulate_variant(
            theme_config,
            a_klines,
            a_instruments,
            hk_klines,
            hk_instruments,
            hold_days,
            "off",
            "stock_signal_theme_vehicle",
            cost_model,
            stop_loss,
            position_fraction,
            2,
            "base",
            warmup_days,
            gate_cache,
            breadth_symbols,
            theme_cache,
        )
        train = [trade for trade in trades if trade.signal_date <= train_end_date]
        validation = [trade for trade in trades if train_end_date < trade.signal_date <= validation_end_date]
        test = [trade for trade in trades if trade.signal_date > validation_end_date]
        variants.append(
            BacktestVariant(
                name=f"stock_signal_theme_vehicle_positions_2_hold_{hold_days}_off",
                hold_days=hold_days,
                max_positions=2,
                cross_market_mode="off",
                signal_mode="stock_signal_theme_vehicle",
                signal_profile="base",
                position_fraction=position_fraction,
                stop_loss=stop_loss,
                all_period=_metrics(trades, a_klines),
                train=_metrics(train, a_klines),
                validation=_metrics(validation, a_klines),
                test=_metrics(test, a_klines),
                trades=trades,
                execution_stats=execution_stats,
            )
        )

    for signal_mode in ("stock_basket", "stock_signal_theme_vehicle"):
        for theme_exit_days in (3, None):
            trades, execution_stats = simulate_variant(
                theme_config,
                a_klines,
                a_instruments,
                hk_klines,
                hk_instruments,
                15,
                "off",
                signal_mode,
                cost_model,
                stop_loss,
                position_fraction,
                2,
                "base",
                warmup_days,
                gate_cache,
                breadth_symbols,
                theme_cache,
                theme_exit_days=theme_exit_days,
            )
            train = [trade for trade in trades if trade.signal_date <= train_end_date]
            validation = [trade for trade in trades if train_end_date < trade.signal_date <= validation_end_date]
            test = [trade for trade in trades if trade.signal_date > validation_end_date]
            exit_label = str(theme_exit_days) if theme_exit_days is not None else "off"
            variants.append(
                BacktestVariant(
                    name=f"{signal_mode}_positions_2_hold_15_off_theme_exit_{exit_label}",
                    hold_days=15,
                    max_positions=2,
                    cross_market_mode="off",
                    signal_mode=signal_mode,
                    signal_profile="base",
                    position_fraction=position_fraction,
                    stop_loss=stop_loss,
                    all_period=_metrics(trades, a_klines),
                    train=_metrics(train, a_klines),
                    validation=_metrics(validation, a_klines),
                    test=_metrics(test, a_klines),
                    trades=trades,
                    execution_stats=execution_stats,
                    theme_exit_days=theme_exit_days,
                )
            )

    for signal_profile in ("loose", "strict"):
        trades, execution_stats = simulate_variant(
            theme_config,
            a_klines,
            a_instruments,
            hk_klines,
            hk_instruments,
            15,
            "off",
            "stock_basket",
            cost_model,
            stop_loss,
            position_fraction,
            2,
            signal_profile,
            warmup_days,
            gate_cache,
            breadth_symbols,
            theme_cache,
        )
        train = [trade for trade in trades if trade.signal_date <= train_end_date]
        validation = [trade for trade in trades if train_end_date < trade.signal_date <= validation_end_date]
        test = [trade for trade in trades if trade.signal_date > validation_end_date]
        variants.append(
            BacktestVariant(
                name=f"stock_basket_positions_2_hold_15_off_{signal_profile}",
                hold_days=15,
                max_positions=2,
                cross_market_mode="off",
                signal_mode="stock_basket",
                signal_profile=signal_profile,
                position_fraction=position_fraction,
                stop_loss=stop_loss,
                all_period=_metrics(trades, a_klines),
                train=_metrics(train, a_klines),
                validation=_metrics(validation, a_klines),
                test=_metrics(test, a_klines),
                trades=trades,
                execution_stats=execution_stats,
            )
        )

    for size_fraction in (0.20, 1 / 3):
        trades, execution_stats = simulate_variant(
            theme_config,
            a_klines,
            a_instruments,
            hk_klines,
            hk_instruments,
            15,
            "off",
            "stock_basket",
            cost_model,
            stop_loss,
            size_fraction,
            2,
            "base",
            warmup_days,
            gate_cache,
            breadth_symbols,
            theme_cache,
        )
        train = [trade for trade in trades if trade.signal_date <= train_end_date]
        validation = [trade for trade in trades if train_end_date < trade.signal_date <= validation_end_date]
        test = [trade for trade in trades if trade.signal_date > validation_end_date]
        variants.append(
            BacktestVariant(
                name=f"stock_basket_positions_2_hold_15_off_size_{size_fraction:.2f}",
                hold_days=15,
                max_positions=2,
                cross_market_mode="off",
                signal_mode="stock_basket",
                signal_profile="base",
                position_fraction=size_fraction,
                stop_loss=stop_loss,
                all_period=_metrics(trades, a_klines),
                train=_metrics(train, a_klines),
                validation=_metrics(validation, a_klines),
                test=_metrics(test, a_klines),
                trades=trades,
                execution_stats=execution_stats,
            )
        )

    for tested_stop_loss in (0.05, 0.06, 0.10):
        trades, execution_stats = simulate_variant(
            theme_config,
            a_klines,
            a_instruments,
            hk_klines,
            hk_instruments,
            15,
            "off",
            "stock_basket",
            cost_model,
            tested_stop_loss,
            position_fraction,
            2,
            "base",
            warmup_days,
            gate_cache,
            breadth_symbols,
            theme_cache,
        )
        train = [trade for trade in trades if trade.signal_date <= train_end_date]
        validation = [trade for trade in trades if train_end_date < trade.signal_date <= validation_end_date]
        test = [trade for trade in trades if trade.signal_date > validation_end_date]
        variants.append(
            BacktestVariant(
                name=f"stock_basket_positions_2_hold_15_off_stop_{tested_stop_loss:.2f}",
                hold_days=15,
                max_positions=2,
                cross_market_mode="off",
                signal_mode="stock_basket",
                signal_profile="base",
                position_fraction=position_fraction,
                stop_loss=tested_stop_loss,
                all_period=_metrics(trades, a_klines),
                train=_metrics(train, a_klines),
                validation=_metrics(validation, a_klines),
                test=_metrics(test, a_klines),
                trades=trades,
                execution_stats=execution_stats,
            )
        )

    stable_increment_holds = 0
    for hold_days in (10, 15, 20):
        baseline = next(
            item
            for item in variants
            if item.signal_mode == "stock_basket"
            and item.max_positions == 2
            and item.hold_days == hold_days
            and item.cross_market_mode == "off"
            and item.signal_profile == "base"
            and item.position_fraction == position_fraction
            and item.stop_loss == stop_loss
        )
        confirmed = next(
            item
            for item in variants
            if item.signal_mode == "stock_basket"
            and item.max_positions == 2
            and item.hold_days == hold_days
            and item.cross_market_mode == "confirm"
            and item.signal_profile == "base"
            and item.position_fraction == position_fraction
            and item.stop_loss == stop_loss
        )
        if (
            (confirmed.validation.cumulative_return or 0) > max(baseline.validation.cumulative_return or 0, 0)
            and (confirmed.test.cumulative_return or 0) > max(baseline.test.cumulative_return or 0, 0)
        ):
            stable_increment_holds += 1
    default_variant = next(
        item
        for item in variants
        if item.signal_mode == "stock_basket"
        and item.max_positions == 2
        and item.hold_days == 15
        and item.cross_market_mode == "off"
        and item.signal_profile == "base"
        and item.position_fraction == position_fraction
        and item.stop_loss == stop_loss
    )
    confirmed_core = next(
        item
        for item in variants
        if item.signal_mode == "stock_basket"
        and item.max_positions == 2
        and item.hold_days == 15
        and item.cross_market_mode == "confirm"
        and item.signal_profile == "base"
        and item.position_fraction == position_fraction
        and item.stop_loss == stop_loss
    )
    etf_proxy_variant = next(
        item
        for item in variants
        if item.signal_mode == "etf_proxy"
        and item.max_positions == 2
        and item.hold_days == 15
        and item.cross_market_mode == "off"
        and item.signal_profile == "base"
        and item.position_fraction == position_fraction
        and item.stop_loss == stop_loss
    )
    signal_vehicle_variants = [
        item
        for item in variants
        if item.signal_mode == "stock_signal_theme_vehicle"
        and item.max_positions == 2
        and item.cross_market_mode == "off"
        and item.signal_profile == "base"
        and item.position_fraction == position_fraction
        and item.stop_loss == stop_loss
    ]
    signal_vehicle_core = next(item for item in signal_vehicle_variants if item.hold_days == 15)
    benchmark = a_klines.get("510300.SH")
    default_folds = _time_folds(default_variant.trades, calendar, benchmark, a_klines, warmup_days)
    etf_folds = _time_folds(etf_proxy_variant.trades, calendar, benchmark, a_klines, warmup_days)
    signal_vehicle_folds = _time_folds(
        signal_vehicle_core.trades,
        calendar,
        benchmark,
        a_klines,
        warmup_days,
    )
    positive_folds = sum((fold.metrics.cumulative_return or 0) > 0 for fold in default_folds)
    excess_positive_folds = sum((fold.excess_return or 0) > 0 for fold in default_folds)
    etf_positive_folds = sum((fold.metrics.cumulative_return or 0) > 0 for fold in etf_folds)
    etf_excess_positive_folds = sum((fold.excess_return or 0) > 0 for fold in etf_folds)
    signal_vehicle_positive_folds = sum(
        (fold.metrics.cumulative_return or 0) > 0 for fold in signal_vehicle_folds
    )
    signal_vehicle_excess_positive_folds = sum(
        (fold.excess_return or 0) > 0 for fold in signal_vehicle_folds
    )
    signal_vehicle_stable_holds = sum(
        (item.validation.cumulative_return or 0) > 0 and (item.test.cumulative_return or 0) > 0
        for item in signal_vehicle_variants
    )
    signal_vehicle_pass = bool(
        signal_vehicle_positive_folds >= 3
        and signal_vehicle_excess_positive_folds >= 2
        and signal_vehicle_stable_holds >= 2
        and signal_vehicle_core.validation.trades >= 8
        and signal_vehicle_core.test.trades >= 10
        and (signal_vehicle_core.validation.cumulative_return or 0) > 0
        and (signal_vehicle_core.test.cumulative_return or 0) > 0
        and (signal_vehicle_core.test.max_drawdown or -1) >= -0.15
    )
    exit_policy_variants_by_mode = {
        signal_mode: [
            item
            for item in variants
            if item.signal_mode == signal_mode
            and item.max_positions == 2
            and item.hold_days == 15
            and item.cross_market_mode == "off"
            and item.signal_profile == "base"
            and item.position_fraction == position_fraction
            and item.stop_loss == stop_loss
            and item.theme_exit_days in {2, 3, None}
        ]
        for signal_mode in ("stock_basket", "stock_signal_theme_vehicle")
    }
    stock_exit_policy_stable = sum(
        (item.validation.cumulative_return or 0) > 0 and (item.test.cumulative_return or 0) > 0
        for item in exit_policy_variants_by_mode["stock_basket"]
    )
    signal_vehicle_exit_policy_stable = sum(
        (item.validation.cumulative_return or 0) > 0 and (item.test.cumulative_return or 0) > 0
        for item in exit_policy_variants_by_mode["stock_signal_theme_vehicle"]
    )
    exit_policy_total = len(exit_policy_variants_by_mode["stock_basket"])
    exit_policy_has_candidate = max(stock_exit_policy_stable, signal_vehicle_exit_policy_stable) >= 2
    position_capacity_variants = [
        item
        for item in variants
        if item.signal_mode == "stock_basket"
        and item.hold_days == 15
        and item.cross_market_mode == "off"
        and item.signal_profile == "base"
        and item.position_fraction == position_fraction
        and item.stop_loss == stop_loss
    ]
    positive_position_capacities = sum(
        (item.validation.cumulative_return or 0) > 0 and (item.test.cumulative_return or 0) > 0
        for item in position_capacity_variants
    )
    signal_profile_variants = [
        item
        for item in variants
        if item.signal_mode == "stock_basket"
        and item.max_positions == 2
        and item.hold_days == 15
        and item.cross_market_mode == "off"
        and item.position_fraction == position_fraction
        and item.stop_loss == stop_loss
    ]
    positive_signal_profiles = sum(
        (item.validation.cumulative_return or 0) > 0 and (item.test.cumulative_return or 0) > 0
        for item in signal_profile_variants
    )
    position_size_variants = [
        item
        for item in variants
        if item.signal_mode == "stock_basket"
        and item.max_positions == 2
        and item.hold_days == 15
        and item.cross_market_mode == "off"
        and item.signal_profile == "base"
        and item.stop_loss == stop_loss
    ]
    positive_position_sizes = sum(
        (item.validation.cumulative_return or 0) > 0 and (item.test.cumulative_return or 0) > 0
        for item in position_size_variants
    )
    stop_loss_variants = [
        item
        for item in variants
        if item.signal_mode == "stock_basket"
        and item.max_positions == 2
        and item.hold_days == 15
        and item.cross_market_mode == "off"
        and item.signal_profile == "base"
        and item.position_fraction == position_fraction
    ]
    positive_stop_losses = sum(
        (item.validation.cumulative_return or 0) > 0 and (item.test.cumulative_return or 0) > 0
        for item in stop_loss_variants
    )
    walk_forward_candidates = [
        item
        for item in variants
        if item.signal_mode == "stock_basket"
        and item.signal_profile == "base"
        and item.position_fraction == position_fraction
        and item.stop_loss == stop_loss
        and item.max_positions in {1, 2, 3}
        and item.hold_days in {10, 15, 20}
        and item.cross_market_mode in {"off", "confirm"}
    ]
    walk_forward = _walk_forward_audit(
        walk_forward_candidates,
        calendar,
        benchmark,
        a_klines,
        warmup_days,
    )
    theme_trade_counts: dict[str, int] = {}
    for trade in default_variant.trades:
        theme_trade_counts[trade.theme] = theme_trade_counts.get(trade.theme, 0) + 1
    doubled_cost_metrics = _metrics_with_cost(
        default_variant.trades,
        cost_model,
        a_klines,
        2.0,
    )
    strategy_return = default_variant.all_period.cumulative_return or 0
    exposure_matched_benchmark_return = _exposure_matched_benchmark_return(default_variant.trades, benchmark)
    robustness_pass = bool(
        positive_folds >= 3
        and excess_positive_folds >= 2
        and etf_positive_folds >= 3
        and etf_excess_positive_folds >= 2
        and positive_position_capacities >= 2
        and positive_signal_profiles >= 2
        and positive_position_sizes >= 2
        and positive_stop_losses >= 3
        and walk_forward.verdict == "滚动选择通过初步门槛"
        and (doubled_cost_metrics.cumulative_return or 0) > 0
        and (default_variant.all_period.max_drawdown or -1) >= -0.15
        and (_top_profit_share(default_variant.trades) or 1) <= 0.65
        and strategy_return > (exposure_matched_benchmark_return or 0)
    )
    robustness = RobustnessAudit(
        default_variant=default_variant.name,
        positive_folds=positive_folds,
        excess_positive_folds=excess_positive_folds,
        total_folds=len(default_folds),
        folds=default_folds,
        doubled_cost_metrics=doubled_cost_metrics,
        exposure_matched_benchmark_return=exposure_matched_benchmark_return,
        top_five_profit_share=_top_profit_share(default_variant.trades),
        theme_trade_counts=dict(sorted(theme_trade_counts.items(), key=lambda item: item[1], reverse=True)),
        etf_proxy_variant=etf_proxy_variant.name,
        etf_proxy_positive_folds=etf_positive_folds,
        etf_proxy_excess_positive_folds=etf_excess_positive_folds,
        etf_proxy_folds=etf_folds,
        signal_vehicle_variant=signal_vehicle_core.name,
        signal_vehicle_positive_folds=signal_vehicle_positive_folds,
        signal_vehicle_excess_positive_folds=signal_vehicle_excess_positive_folds,
        signal_vehicle_folds=signal_vehicle_folds,
        signal_vehicle_stable_holds=signal_vehicle_stable_holds,
        signal_vehicle_total_holds=len(signal_vehicle_variants),
        signal_vehicle_verdict=(
            "ETF执行达到初步挑战者门槛，保持模拟观察"
            if signal_vehicle_pass
            else "ETF执行未通过跨时期门槛，不进入生产"
        ),
        stock_exit_policy_stable=stock_exit_policy_stable,
        signal_vehicle_exit_policy_stable=signal_vehicle_exit_policy_stable,
        exit_policy_variants_per_mode=exit_policy_total,
        exit_policy_verdict=(
            "退出结构存在跨期候选，继续滚动模拟验证"
            if exit_policy_has_candidate
            else "退出结构对验证和留出不稳定，保持生产默认值"
        ),
        positive_position_capacities=positive_position_capacities,
        total_position_capacities=len(position_capacity_variants),
        positive_signal_profiles=positive_signal_profiles,
        total_signal_profiles=len(signal_profile_variants),
        positive_position_sizes=positive_position_sizes,
        total_position_sizes=len(position_size_variants),
        positive_stop_losses=positive_stop_losses,
        total_stop_losses=len(stop_loss_variants),
        walk_forward=walk_forward,
        exit_diagnostics=_group_diagnostics(default_variant.trades, "exit"),
        gate_diagnostics=_group_diagnostics(default_variant.trades, "gate"),
        selection_attribution=_selection_attribution(
            default_variant.trades,
            train_end_date,
            validation_end_date,
        ),
        verdict=("核心规则通过第一轮反过拟合审计" if robustness_pass else "核心规则未通过反过拟合审计，继续研究"),
    )
    confirmed_core_folds = _time_folds(confirmed_core.trades, calendar, benchmark, a_klines, warmup_days)
    accept = bool(
        stable_increment_holds >= 2
        and sum((fold.metrics.cumulative_return or 0) > 0 for fold in confirmed_core_folds) >= 3
        and confirmed_core.validation.trades >= 8
        and confirmed_core.test.trades >= 10
        and (confirmed_core.validation.cumulative_return or 0) > 0
        and (confirmed_core.test.cumulative_return or 0) > 0
        and (confirmed_core.test.max_drawdown or -1) >= -0.15
    )
    cross_market_verdict = "A/H确认达到历史挑战者门槛，保持模拟观察" if accept else "A/H确认信号暂不进入生产评分"
    current_cost = apply_execution_costs(
        100.0,
        100.0,
        cn_market_date_from_ms(usable_dates[-1]) or "2026-01-01",
        cn_market_date_from_ms(usable_dates[-1]) or "2026-01-01",
        cost_model.account_capital * position_fraction / 3,
        is_fund=False,
        cost_model=cost_model,
    )
    return StrategyBacktestReport(
        generated_for="A股主线轮动与A/H确认增量",
        transaction_cost=-(current_cost["net_return"]),
        stop_loss=stop_loss,
        position_fraction=position_fraction,
        warmup_days=warmup_days,
        breadth_symbols=len(breadth_symbols),
        split_dates={
            "train_end": train_end_date,
            "validation_end": validation_end_date,
            "test_end": cn_market_date_from_ms(usable_dates[-1]) or "",
        },
        benchmark_returns={
            "all": _benchmark_return(a_klines.get("510300.SH"), usable_dates[0], usable_dates[-1]),
            "train": _benchmark_return(a_klines.get("510300.SH"), usable_dates[0], train_end),
            "validation": _benchmark_return(a_klines.get("510300.SH"), train_end, validation_end),
            "test": _benchmark_return(a_klines.get("510300.SH"), validation_end, usable_dates[-1]),
        },
        benchmark_drawdowns={
            "all": _series_drawdown(a_klines.get("510300.SH"), usable_dates[0], usable_dates[-1]),
            "train": _series_drawdown(a_klines.get("510300.SH"), usable_dates[0], train_end),
            "validation": _series_drawdown(a_klines.get("510300.SH"), train_end, validation_end),
            "test": _series_drawdown(a_klines.get("510300.SH"), validation_end, usable_dates[-1]),
        },
        variants=variants,
        robustness=robustness,
        verdict=robustness.verdict,
        cross_market_verdict=cross_market_verdict,
        cost_model=cost_model.assumptions(),
        notes=[
            "所有信号使用当日收盘前可见数据；等待最多5个交易日完成回踩收复或突破收盘确认，再于下一交易日开盘成交。",
            "固定规则同时测试10/15/20日，不能只选择单一最优持有期。",
            "滚动参数选择每一步只使用此前时间折，且训练交易必须在选择截止日前完成，避免跨边界读取未来退出结果。",
            "回测同时检查最多一仓、两仓和三仓；首笔只使用计划仓位的1/3，橙色闸门再减半，并审计20%、25%和33%三档计划风险预算。",
            "主线连续两日确认后才入场；市场闸门转红时禁止新仓，已有仓位继续由主线失效位、8%硬失效位和到期规则管理。",
            "A股交易逐笔计入券商佣金及最低5元、证管费、经手费、过户费、卖出印花税和双边滑点；ETF按基金费率且不收印花税。",
            "封死涨停或停牌时不买入并取消该计划；封死跌停或停牌时不假设能够卖出，顺延到首个可成交交易日。",
            "主题个股成分和市场广度样本来自当前可见股票池，仍有退市股票缺失造成的幸存者偏差。",
            "历史风险警示名称不完整，ST状态无法逐日恢复；能够从当日名称识别时按主板5%限制处理，否则按所属板块普通涨跌幅处理。",
            "未使用历史财务公告和历史政策新闻，回测只检验价格主线与A/H确认增量。",
            "主线内选股归因使用每个主题配置中首个具备完整同期行情的ETF，并按个股完全相同的进出日期、仓位和ETF交易成本计算；无ETF主题不纳入可比交易。",
            "个股先行信号+主题ETF执行是独立挑战者：主线和个股只负责产生触发，实际成交、止损和退出均使用主题ETF自身行情；即使过线也只进入模拟观察。",
            "退出状态机额外审计连续2日、连续3日和不按主题排名退出三档；不按主题排名退出仍保留8%硬失效位与固定持有到期，审计结果不会自动修改生产默认值。",
            f"A/H确认在 {stable_increment_holds}/3 个持有期使验证段、最终留出段累计收益均为正且高于未确认版；"
            "达到历史门槛也只进入模拟观察，不直接提高实盘评分。",
        ],
    )
