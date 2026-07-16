from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from statistics import fmean, median
from typing import Any

from .config import configured_symbols, theme_candidate_symbols, theme_symbol_map
from .cross_market import build_cross_market_report
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
    all_period: BacktestMetrics
    train: BacktestMetrics
    validation: BacktestMetrics
    test: BacktestMetrics
    trades: list[StrategyTrade] = field(default_factory=list)


@dataclass
class FoldResult:
    name: str
    start_date: str
    end_date: str
    metrics: BacktestMetrics
    benchmark_return: float | None
    benchmark_drawdown: float | None
    excess_return: float | None


@dataclass
class RobustnessAudit:
    default_variant: str
    positive_folds: int
    excess_positive_folds: int
    total_folds: int
    folds: list[FoldResult]
    doubled_cost_metrics: BacktestMetrics
    top_five_profit_share: float | None
    theme_trade_counts: dict[str, int]
    etf_proxy_variant: str
    etf_proxy_positive_folds: int
    etf_proxy_excess_positive_folds: int
    etf_proxy_folds: list[FoldResult]
    positive_position_capacities: int
    total_position_capacities: int
    positive_signal_profiles: int
    total_signal_profiles: int
    positive_position_sizes: int
    total_position_sizes: int
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
        f"- 交易成本：{_percent(report.transaction_cost)}",
        f"- 单笔最大资金占比：{_percent(report.position_fraction)}",
        f"- 硬失效位：{_percent(report.stop_loss)}",
        f"- 历史市场广度样本：{report.breadth_symbols}只",
        f"- 时间切分：训练截至 {report.split_dates['train_end']}，验证截至 {report.split_dates['validation_end']}，最终留出截至 {report.split_dates['test_end']}",
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
    lines.extend(
        [
            "",
            "## 反过拟合审计",
            "",
            f"- 核心方案：`{report.robustness.default_variant}`",
            f"- 时间折为正：{report.robustness.positive_folds}/{report.robustness.total_folds}",
            f"- 跑赢沪深300ETF的时间折：{report.robustness.excess_positive_folds}/{report.robustness.total_folds}",
            f"- 双倍成本全期收益：{_percent(report.robustness.doubled_cost_metrics.cumulative_return)}",
            f"- 前五笔盈利占全部正收益：{_percent(report.robustness.top_five_profit_share)}",
            f"- ETF代理方案：`{report.robustness.etf_proxy_variant}`，时间折为正 "
            f"{report.robustness.etf_proxy_positive_folds}/{len(report.robustness.etf_proxy_folds)}，跑赢基准 "
            f"{report.robustness.etf_proxy_excess_positive_folds}/{len(report.robustness.etf_proxy_folds)}",
            f"- 仓位容量稳定性：{report.robustness.positive_position_capacities}/"
            f"{report.robustness.total_position_capacities} 档在验证段和留出段均为正",
            f"- 入场强度稳定性：{report.robustness.positive_signal_profiles}/"
            f"{report.robustness.total_signal_profiles} 档在验证段和留出段均为正",
            f"- 单仓风险预算稳定性：{report.robustness.positive_position_sizes}/"
            f"{report.robustness.total_position_sizes} 档在验证段和留出段均为正",
            f"- 审计结论：**{report.robustness.verdict}**",
            "",
            "| 方案 | 时间折 | 起始 | 结束 | 交易数 | 收益 | 回撤 | 沪深300ETF | 基准回撤 | 超额 |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for variant_name, folds in (
        (report.robustness.default_variant, report.robustness.folds),
        (report.robustness.etf_proxy_variant, report.robustness.etf_proxy_folds),
    ):
        for fold in folds:
            lines.append(
                f"| {variant_name} | {fold.name} | {fold.start_date} | {fold.end_date} | "
                f"{fold.metrics.trades} | {_percent(fold.metrics.cumulative_return)} | "
                f"{_percent(fold.metrics.max_drawdown)} | {_percent(fold.benchmark_return)} | "
                f"{_percent(fold.benchmark_drawdown)} | {_percent(fold.excess_return)} |"
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
            _, shares, notional = position
            transaction_cost = max(0.0, trade.gross_return - trade.net_return)
            cash += shares * trade.exit_price - notional * transaction_cost

        opening_equity = cash
        for trade, shares, _ in active.values():
            series = klines.get(trade.symbol)
            price = _price_on_or_before(series, timestamp, "open") if series else None
            if price is not None:
                opening_equity += shares * price
        for trade_id, trade in entries.get(date, []):
            notional = min(cash, opening_equity * trade.position_fraction)
            if notional <= 0:
                continue
            cash -= notional
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
    transaction_cost: float,
    klines: dict[str, KlineSeries],
) -> BacktestMetrics:
    adjusted = [
        StrategyTrade(
            **{
                **asdict(trade),
                "net_return": trade.gross_return - transaction_cost,
                "portfolio_return": (trade.gross_return - transaction_cost) * trade.position_fraction,
            }
        )
        for trade in trades
    ]
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


def simulate_variant(
    theme_config: dict[str, Any],
    a_klines: dict[str, KlineSeries],
    a_instruments: dict[str, dict[str, Any]],
    hk_klines: dict[str, KlineSeries],
    hk_instruments: dict[str, dict[str, Any]],
    hold_days: int,
    cross_market_mode: str,
    signal_mode: str,
    transaction_cost: float,
    stop_loss: float,
    position_fraction: float,
    max_positions: int,
    signal_profile: str,
    warmup_days: int,
    gate_cache: dict[int, str],
    breadth_symbols: set[str],
    theme_cache: dict[tuple[str, int], set[str]],
) -> list[StrategyTrade]:
    strategy_config = _etf_proxy_config(theme_config) if signal_mode == "etf_proxy" else theme_config
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
    planned_positions: list[tuple[int, str, str]] = []
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
            trade_position_fraction = position_fraction if entry_gate == "green" else position_fraction / 2
            exit_index = entry_index + hold_days
            entry_timestamp = calendar[entry_index]
            exit_timestamp = calendar[exit_index]
            series = a_klines[candidate.symbol]
            entry_price = _price_at(series, entry_timestamp, "open")
            if not entry_price or entry_price <= 0:
                excluded_symbols.add(candidate.symbol)
                continue
            exit_reason = f"固定持有{hold_days}日"
            exit_field = "close"
            inactive_theme_days = 0
            for check_index in range(entry_index, exit_index):
                check_close = _price_at(series, calendar[check_index], "close")
                if check_close is not None and check_close <= entry_price * (1 - stop_loss):
                    exit_timestamp = calendar[check_index + 1]
                    exit_field = "open"
                    exit_reason = f"收盘跌破{stop_loss * 100:.0f}%失效位，次日开盘退出"
                    exit_index = check_index + 1
                    break
                check_timestamp = calendar[check_index]
                if theme_name in active_themes(check_timestamp):
                    inactive_theme_days = 0
                else:
                    inactive_theme_days += 1
                if inactive_theme_days >= 2:
                    exit_timestamp = calendar[check_index + 1]
                    exit_field = "open"
                    exit_reason = "主线连续两日退出前三或失去候选身份，次日开盘退出"
                    exit_index = check_index + 1
                    break
            exit_price = _price_at(series, exit_timestamp, exit_field)
            if not exit_price:
                excluded_symbols.add(candidate.symbol)
                continue
            gross_return = exit_price / entry_price - 1
            trades.append(
                StrategyTrade(
                    symbol=candidate.symbol,
                    name=candidate.name,
                    theme=theme_name,
                    signal_date=cn_market_date_from_ms(cutoff) or "",
                    entry_date=cn_market_date_from_ms(entry_timestamp) or "",
                    exit_date=cn_market_date_from_ms(exit_timestamp) or "",
                    entry_price=entry_price,
                    exit_price=exit_price,
                    gross_return=gross_return,
                    net_return=gross_return - transaction_cost,
                    portfolio_return=(gross_return - transaction_cost) * trade_position_fraction,
                    position_fraction=trade_position_fraction,
                    exit_reason=exit_reason,
                    cross_market_status=status,
                )
            )
            planned_positions.append((exit_index, candidate.symbol, theme_name))
            excluded_symbols.add(candidate.symbol)
            excluded_themes.add(theme_name)
        index += 1
    return trades


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
        metrics = _metrics(fold_trades, klines)
        excess_return = (
            metrics.cumulative_return - benchmark_return
            if metrics.cumulative_return is not None and benchmark_return is not None
            else None
        )
        results.append(
            FoldResult(
                name=f"fold_{index + 1}",
                start_date=start_date,
                end_date=end_date,
                metrics=metrics,
                benchmark_return=benchmark_return,
                benchmark_drawdown=_series_drawdown(benchmark, start_timestamp, end_timestamp),
                excess_return=excess_return,
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
    transaction_cost: float = 0.003,
    stop_loss: float = 0.08,
    position_fraction: float = 0.25,
    warmup_days: int = 140,
    breadth_symbols: set[str] | None = None,
) -> StrategyBacktestReport:
    breadth_symbols = breadth_symbols or set()
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
                    trades = simulate_variant(
                        theme_config,
                        a_klines,
                        a_instruments,
                        hk_klines,
                        hk_instruments,
                        hold_days,
                        mode,
                        signal_mode,
                        transaction_cost,
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
                            all_period=_metrics(trades, a_klines),
                            train=_metrics(train, a_klines),
                            validation=_metrics(validation, a_klines),
                            test=_metrics(test, a_klines),
                            trades=trades,
                        )
                    )

    for signal_profile in ("loose", "strict"):
        trades = simulate_variant(
            theme_config,
            a_klines,
            a_instruments,
            hk_klines,
            hk_instruments,
            15,
            "off",
            "stock_basket",
            transaction_cost,
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
                all_period=_metrics(trades, a_klines),
                train=_metrics(train, a_klines),
                validation=_metrics(validation, a_klines),
                test=_metrics(test, a_klines),
                trades=trades,
            )
        )

    for size_fraction in (0.20, 1 / 3):
        trades = simulate_variant(
            theme_config,
            a_klines,
            a_instruments,
            hk_klines,
            hk_instruments,
            15,
            "off",
            "stock_basket",
            transaction_cost,
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
                all_period=_metrics(trades, a_klines),
                train=_metrics(train, a_klines),
                validation=_metrics(validation, a_klines),
                test=_metrics(test, a_klines),
                trades=trades,
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
        )
        if (confirmed.validation.avg_return or 0) > (baseline.validation.avg_return or 0) and (
            confirmed.test.avg_return or 0
        ) > (baseline.test.avg_return or 0) + 0.001:
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
    )
    benchmark = a_klines.get("510300.SH")
    default_folds = _time_folds(default_variant.trades, calendar, benchmark, a_klines, warmup_days)
    etf_folds = _time_folds(etf_proxy_variant.trades, calendar, benchmark, a_klines, warmup_days)
    positive_folds = sum((fold.metrics.cumulative_return or 0) > 0 for fold in default_folds)
    excess_positive_folds = sum((fold.excess_return or 0) > 0 for fold in default_folds)
    etf_positive_folds = sum((fold.metrics.cumulative_return or 0) > 0 for fold in etf_folds)
    etf_excess_positive_folds = sum((fold.excess_return or 0) > 0 for fold in etf_folds)
    position_capacity_variants = [
        item
        for item in variants
        if item.signal_mode == "stock_basket"
        and item.hold_days == 15
        and item.cross_market_mode == "off"
        and item.signal_profile == "base"
        and item.position_fraction == position_fraction
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
    ]
    positive_position_sizes = sum(
        (item.validation.cumulative_return or 0) > 0 and (item.test.cumulative_return or 0) > 0
        for item in position_size_variants
    )
    theme_trade_counts: dict[str, int] = {}
    for trade in default_variant.trades:
        theme_trade_counts[trade.theme] = theme_trade_counts.get(trade.theme, 0) + 1
    doubled_cost_metrics = _metrics_with_cost(
        default_variant.trades,
        transaction_cost * 2,
        a_klines,
    )
    strategy_return = default_variant.all_period.cumulative_return or 0
    strategy_drawdown = abs(default_variant.all_period.max_drawdown or -1)
    benchmark_return = _benchmark_return(benchmark, usable_dates[0], usable_dates[-1]) or 0
    benchmark_drawdown = abs(_series_drawdown(benchmark, usable_dates[0], usable_dates[-1]) or -1)
    strategy_return_to_drawdown = strategy_return / strategy_drawdown if strategy_drawdown else 0
    benchmark_return_to_drawdown = benchmark_return / benchmark_drawdown if benchmark_drawdown else 0
    robustness_pass = bool(
        positive_folds >= 3
        and excess_positive_folds >= 2
        and etf_positive_folds >= 3
        and etf_excess_positive_folds >= 2
        and positive_position_capacities >= 2
        and positive_signal_profiles >= 2
        and positive_position_sizes >= 2
        and (doubled_cost_metrics.cumulative_return or 0) > 0
        and (default_variant.all_period.max_drawdown or -1) >= -0.15
        and (_top_profit_share(default_variant.trades) or 1) <= 0.65
        and strategy_return_to_drawdown >= benchmark_return_to_drawdown
    )
    robustness = RobustnessAudit(
        default_variant=default_variant.name,
        positive_folds=positive_folds,
        excess_positive_folds=excess_positive_folds,
        total_folds=len(default_folds),
        folds=default_folds,
        doubled_cost_metrics=doubled_cost_metrics,
        top_five_profit_share=_top_profit_share(default_variant.trades),
        theme_trade_counts=dict(sorted(theme_trade_counts.items(), key=lambda item: item[1], reverse=True)),
        etf_proxy_variant=etf_proxy_variant.name,
        etf_proxy_positive_folds=etf_positive_folds,
        etf_proxy_excess_positive_folds=etf_excess_positive_folds,
        etf_proxy_folds=etf_folds,
        positive_position_capacities=positive_position_capacities,
        total_position_capacities=len(position_capacity_variants),
        positive_signal_profiles=positive_signal_profiles,
        total_signal_profiles=len(signal_profile_variants),
        positive_position_sizes=positive_position_sizes,
        total_position_sizes=len(position_size_variants),
        verdict=("核心规则通过第一轮反过拟合审计" if robustness_pass else "核心规则未通过反过拟合审计，继续研究"),
    )
    accept = bool(
        stable_increment_holds >= 2
        and default_variant.validation.trades >= 8
        and default_variant.test.trades >= 10
        and (default_variant.validation.avg_return or 0) > 0
        and (default_variant.test.avg_return or 0) > 0
        and (default_variant.test.max_drawdown or -1) >= -0.15
    )
    cross_market_verdict = "A/H确认信号通过初步样本外门槛" if accept else "A/H确认信号暂不进入生产评分"
    return StrategyBacktestReport(
        generated_for="A股主线轮动与A/H确认增量",
        transaction_cost=transaction_cost,
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
        notes=[
            "所有信号使用当日收盘前可见数据，下一交易日开盘成交。",
            "固定规则同时测试10/15/20日，不能只选择单一最优持有期。",
            "回测同时检查最多一仓、两仓和三仓；基准单仓使用总资金1/4，橙色闸门单仓减半，并审计20%、25%和33%三档风险预算。",
            "主线连续两日确认后才入场；市场闸门转红时禁止新仓，已有仓位继续由主线失效位、8%硬失效位和到期规则管理。",
            "主题个股成分和市场广度样本来自当前可见股票池，仍有退市股票缺失造成的幸存者偏差。",
            "未使用历史财务公告和历史政策新闻，回测只检验价格主线与A/H确认增量。",
            f"A/H确认在 {stable_increment_holds}/3 个持有期同时改善验证段和最终留出段。",
        ],
    )
