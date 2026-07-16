from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass, field
from statistics import fmean, median
from typing import Any

from .config import theme_candidate_symbols, theme_symbol_map
from .cross_market import build_cross_market_report
from .market import build_theme_snapshots, compute_symbol_snapshot
from .market_context import build_market_pulses
from .market_structure import build_market_structure
from .models import KlineSeries, SymbolSnapshot, cn_market_date_from_ms
from .risk_gate import build_trading_gate


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
    cross_market_mode: str
    all_period: BacktestMetrics
    train: BacktestMetrics
    validation: BacktestMetrics
    test: BacktestMetrics
    trades: list[StrategyTrade] = field(default_factory=list)


@dataclass
class StrategyBacktestReport:
    generated_for: str
    transaction_cost: float
    stop_loss: float
    position_fraction: float
    warmup_days: int
    split_dates: dict[str, str]
    benchmark_returns: dict[str, float | None]
    variants: list[BacktestVariant]
    verdict: str
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
        f"- 交易成本：{_percent(report.transaction_cost)}",
        f"- 单笔资金占比：{_percent(report.position_fraction)}",
        f"- 硬失效位：{_percent(report.stop_loss)}",
        f"- 时间切分：训练截至 {report.split_dates['train_end']}，验证截至 {report.split_dates['validation_end']}，最终留出截至 {report.split_dates['test_end']}",
        "",
        "## 基准",
        "",
        "| 区间 | 沪深300ETF收益 |",
        "| --- | ---: |",
    ]
    for name, label in (("all", "全期"), ("train", "训练"), ("validation", "验证"), ("test", "最终留出")):
        lines.append(f"| {label} | {_percent(report.benchmark_returns.get(name))} |")
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


def _metrics(trades: list[StrategyTrade]) -> BacktestMetrics:
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
    gains = sum(value for value in returns if value > 0)
    losses = -sum(value for value in returns if value < 0)
    return BacktestMetrics(
        trades=len(trades),
        win_rate=sum(value > 0 for value in returns) / len(returns),
        avg_return=fmean(returns),
        median_return=median(returns),
        cumulative_return=equity - 1,
        max_drawdown=max_drawdown,
        profit_factor=(gains / losses) if losses > 0 else None,
        start_date=trades[0].signal_date,
        end_date=trades[-1].exit_date,
    )


def _calendar(klines: dict[str, KlineSeries], preferred: str = "000001.SH") -> list[int]:
    if preferred in klines:
        return klines[preferred].timestamp
    return max(klines.values(), key=lambda series: len(series.timestamp)).timestamp


def _candidate(
    theme_config: dict[str, Any],
    themes: list[Any],
    snapshots: dict[str, SymbolSnapshot],
    cross_status: dict[str, str],
    cross_market_mode: str,
) -> tuple[SymbolSnapshot, str, str | None] | None:
    config_by_theme = {str(item["name"]): item for item in theme_config.get("themes", [])}
    for theme in themes[:3]:
        if theme.status not in {"主线成立", "主线候选"}:
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
                and item.symbol.endswith((".SH", ".SZ", ".BJ"))
                and item.ret_5d is not None
                and 0 <= item.ret_5d < 0.15
                and item.ret_20d is not None
                and item.ret_20d > 0.03
                and item.amount_ratio is not None
                and item.amount_ratio >= 0.90
                and item.high_proximity_20d is not None
                and item.high_proximity_20d > -0.08
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


def simulate_variant(
    theme_config: dict[str, Any],
    a_klines: dict[str, KlineSeries],
    a_instruments: dict[str, dict[str, Any]],
    hk_klines: dict[str, KlineSeries],
    hk_instruments: dict[str, dict[str, Any]],
    hold_days: int,
    cross_market_mode: str,
    transaction_cost: float,
    stop_loss: float,
    position_fraction: float,
    warmup_days: int,
    gate_cache: dict[int, str],
) -> list[StrategyTrade]:
    calendar = _calendar(a_klines)
    symbol_to_themes = theme_symbol_map(theme_config)
    trades: list[StrategyTrade] = []
    next_available_index = warmup_days
    index = warmup_days
    while index < len(calendar) - hold_days - 1:
        if index < next_available_index:
            index += 1
            continue
        cutoff = calendar[index]
        current_klines = _market_slice(a_klines, cutoff)
        snapshots = _snapshots(current_klines, a_instruments, symbol_to_themes)
        themes = build_theme_snapshots(theme_config, snapshots)
        pulses = build_market_pulses(theme_config, snapshots)
        structure = build_market_structure(theme_config, current_klines)
        gate = build_trading_gate(theme_config, snapshots, pulses, structure)
        gate_cache[cutoff] = gate.level
        if gate.level == "red":
            index += 1
            continue

        hk_current = _market_slice(hk_klines, cutoff)
        cross = build_cross_market_report(theme_config, hk_current, hk_instruments, themes, snapshots)
        cross_status = {item.theme: item.status for item in cross.themes}
        selected = _candidate(theme_config, themes, snapshots, cross_status, cross_market_mode)
        if selected is None:
            index += 1
            continue
        candidate, theme_name, status = selected
        entry_index = index + 1
        exit_index = entry_index + hold_days
        entry_timestamp = calendar[entry_index]
        exit_timestamp = calendar[exit_index]
        series = a_klines[candidate.symbol]
        entry_price = _price_at(series, entry_timestamp, "open")
        if not entry_price or entry_price <= 0:
            index += 1
            continue
        exit_reason = f"固定持有{hold_days}日"
        exit_field = "close"
        for check_index in range(entry_index, exit_index):
            check_close = _price_at(series, calendar[check_index], "close")
            if check_close is not None and check_close <= entry_price * (1 - stop_loss):
                exit_timestamp = calendar[check_index + 1]
                exit_field = "open"
                exit_reason = f"收盘跌破{stop_loss * 100:.0f}%失效位，次日开盘退出"
                exit_index = check_index + 1
                break
            check_timestamp = calendar[check_index]
            check_gate = gate_cache.get(check_timestamp)
            if check_gate is None:
                check_klines = _market_slice(a_klines, check_timestamp)
                check_snapshots = _snapshots(check_klines, a_instruments, symbol_to_themes)
                check_pulses = build_market_pulses(theme_config, check_snapshots)
                check_structure = build_market_structure(theme_config, check_klines)
                check_gate = build_trading_gate(
                    theme_config,
                    check_snapshots,
                    check_pulses,
                    check_structure,
                ).level
                gate_cache[check_timestamp] = check_gate
            if check_gate == "red":
                exit_timestamp = calendar[check_index + 1]
                exit_field = "open"
                exit_reason = "市场闸门转红，次日开盘退出"
                exit_index = check_index + 1
                break
        exit_price = _price_at(series, exit_timestamp, exit_field)
        if not exit_price:
            index += 1
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
                portfolio_return=(gross_return - transaction_cost) * position_fraction,
                exit_reason=exit_reason,
                cross_market_status=status,
            )
        )
        next_available_index = exit_index + 1
        index = next_available_index
    return trades


def run_strategy_backtest(
    theme_config: dict[str, Any],
    a_klines: dict[str, KlineSeries],
    a_instruments: dict[str, dict[str, Any]],
    hk_klines: dict[str, KlineSeries],
    hk_instruments: dict[str, dict[str, Any]],
    transaction_cost: float = 0.003,
    stop_loss: float = 0.08,
    position_fraction: float = 1 / 3,
    warmup_days: int = 140,
) -> StrategyBacktestReport:
    calendar = _calendar(a_klines)
    usable_dates = calendar[warmup_days:]
    train_end = usable_dates[int(len(usable_dates) * 0.60)]
    validation_end = usable_dates[int(len(usable_dates) * 0.80)]
    train_end_date = cn_market_date_from_ms(train_end) or ""
    validation_end_date = cn_market_date_from_ms(validation_end) or ""

    variants: list[BacktestVariant] = []
    gate_cache: dict[int, str] = {}
    for hold_days in (10, 15, 20):
        for mode in ("off", "confirm"):
            trades = simulate_variant(
                theme_config,
                a_klines,
                a_instruments,
                hk_klines,
                hk_instruments,
                hold_days,
                mode,
                transaction_cost,
                stop_loss,
                position_fraction,
                warmup_days,
                gate_cache,
            )
            train = [trade for trade in trades if trade.signal_date <= train_end_date]
            validation = [
                trade for trade in trades if train_end_date < trade.signal_date <= validation_end_date
            ]
            test = [trade for trade in trades if trade.signal_date > validation_end_date]
            variants.append(
                BacktestVariant(
                    name=f"hold_{hold_days}_{mode}",
                    hold_days=hold_days,
                    cross_market_mode=mode,
                    all_period=_metrics(trades),
                    train=_metrics(train),
                    validation=_metrics(validation),
                    test=_metrics(test),
                    trades=trades,
                )
            )

    stable_increment_holds = 0
    for hold_days in (10, 15, 20):
        baseline = next(item for item in variants if item.hold_days == hold_days and item.cross_market_mode == "off")
        confirmed = next(
            item for item in variants if item.hold_days == hold_days and item.cross_market_mode == "confirm"
        )
        if (
            (confirmed.validation.avg_return or 0) > (baseline.validation.avg_return or 0)
            and (confirmed.test.avg_return or 0) > (baseline.test.avg_return or 0) + 0.001
        ):
            stable_increment_holds += 1
    default_variant = next(
        item for item in variants if item.hold_days == 15 and item.cross_market_mode == "confirm"
    )
    accept = bool(
        stable_increment_holds >= 2
        and default_variant.validation.trades >= 8
        and default_variant.test.trades >= 10
        and (default_variant.validation.avg_return or 0) > 0
        and (default_variant.test.avg_return or 0) > 0
        and (default_variant.test.max_drawdown or -1) >= -0.15
    )
    verdict = "A/H确认信号通过初步样本外门槛" if accept else "A/H确认信号暂不进入生产评分"
    return StrategyBacktestReport(
        generated_for="A股主线轮动与A/H确认增量",
        transaction_cost=transaction_cost,
        stop_loss=stop_loss,
        position_fraction=position_fraction,
        warmup_days=warmup_days,
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
        variants=variants,
        verdict=verdict,
        notes=[
            "所有信号使用当日收盘前可见数据，下一交易日开盘成交。",
            "固定规则同时测试10/15/20日，不能只选择单一最优持有期。",
            "单笔只使用总资金1/3；持仓期间市场闸门转红或收盘跌破8%失效位，次日开盘退出。",
            "当前主题成分使用现行配置，存在历史成分幸存者偏差；通过本回测也不能直接称为可实盘策略。",
            "未使用历史财务公告和历史政策新闻，回测只检验价格主线与A/H确认增量。",
            f"A/H确认在 {stable_increment_holds}/3 个持有期同时改善验证段和最终留出段。",
        ],
    )
