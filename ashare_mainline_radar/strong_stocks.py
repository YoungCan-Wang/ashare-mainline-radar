from __future__ import annotations

from statistics import mean, median
from typing import Any

from .config import theme_candidate_symbols
from .models import (
    BacktestSummary,
    KlineSeries,
    StrongStockCandidate,
    StrongStockReport,
    SymbolSnapshot,
    ThemeSnapshot,
    cn_market_date_from_ms,
)
from .strategy_rules import BASE_ENTRY_PROFILE


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current / previous) - 1


def _date_from_ms(value: int | None) -> str | None:
    return cn_market_date_from_ms(value)


def _signal_metrics(series: KlineSeries, idx: int) -> dict[str, float] | None:
    if idx < 20 or idx >= len(series.close):
        return None
    close = series.close
    amount = series.amount
    high = series.high
    ret_5d = _pct_change(close[idx], close[idx - 5])
    ret_20d = _pct_change(close[idx], close[idx - 20])
    amount_ma5 = _avg(amount[idx - 4 : idx + 1])
    amount_ma20 = _avg(amount[idx - 19 : idx + 1])
    amount_ratio = (amount_ma5 / amount_ma20) if amount_ma5 is not None and amount_ma20 else None
    high_20d = max(high[idx - 19 : idx + 1])
    high_proximity = _pct_change(close[idx], high_20d)
    if ret_5d is None or ret_20d is None or amount_ratio is None or high_proximity is None:
        return None
    score = 50.0
    score += min(24.0, max(-12.0, ret_20d / 0.18 * 24.0))
    score += min(18.0, max(-10.0, ret_5d / 0.08 * 18.0))
    score += min(16.0, max(-8.0, (amount_ratio - 1.0) * 24.0))
    score += min(10.0, max(-8.0, (1.0 + high_proximity / 0.08) * 10.0))
    return {
        "ret_5d": ret_5d,
        "ret_20d": ret_20d,
        "amount_ratio": amount_ratio,
        "high_proximity": high_proximity,
        "score": max(0.0, min(100.0, score)),
    }


def _is_signal(metrics: dict[str, float]) -> bool:
    return (
        metrics["ret_20d"] >= 0.03
        and metrics["ret_5d"] >= BASE_ENTRY_PROFILE["min_ret_5d"]
        and metrics["amount_ratio"] >= BASE_ENTRY_PROFILE["min_amount_ratio"]
        and metrics["high_proximity"] >= BASE_ENTRY_PROFILE["min_high_proximity"]
        and metrics["score"] >= 62.0
    )


def _candidate_reasons(snapshot: SymbolSnapshot, backtest: BacktestSummary) -> list[str]:
    reasons: list[str] = []
    if snapshot.ret_20d is not None and snapshot.ret_20d > 0:
        reasons.append(f"20日涨幅 {snapshot.ret_20d * 100:.2f}%")
    if snapshot.ret_5d is not None and snapshot.ret_5d > 0:
        reasons.append(f"5日涨幅 {snapshot.ret_5d * 100:.2f}%")
    if snapshot.amount_ratio is not None and snapshot.amount_ratio >= 1:
        reasons.append(f"成交热度 {snapshot.amount_ratio:.2f}x")
    if snapshot.high_proximity_20d is not None and snapshot.high_proximity_20d >= -0.05:
        reasons.append("接近20日高位")
    if backtest.signals:
        win = "n/a" if backtest.win_rate is None else f"{backtest.win_rate * 100:.1f}%"
        avg = "n/a" if backtest.avg_return is None else f"{backtest.avg_return * 100:.2f}%"
        reasons.append(f"历史信号 {backtest.signals} 次，胜率 {win}，均值 {avg}")
    return reasons


def backtest_symbol(
    symbol: str,
    name: str,
    theme: str,
    series: KlineSeries,
    hold_days: int = 5,
) -> BacktestSummary:
    returns: list[float] = []
    drawdowns: list[float] = []
    last_signal_date: str | None = None
    idx = 20
    while idx + hold_days < len(series.close):
        metrics = _signal_metrics(series, idx)
        if metrics and _is_signal(metrics):
            entry_idx = idx + 1
            exit_idx = idx + hold_days
            entry = series.open[entry_idx] if entry_idx < len(series.open) else series.close[entry_idx]
            exit_price = series.close[exit_idx]
            if entry:
                returns.append((exit_price / entry) - 1)
                holding_lows = series.low[entry_idx : exit_idx + 1]
                if holding_lows:
                    drawdowns.append((min(holding_lows) / entry) - 1)
                last_signal_date = _date_from_ms(series.timestamp[idx] if idx < len(series.timestamp) else None)
            idx += hold_days
            continue
        idx += 1

    return BacktestSummary(
        symbol=symbol,
        name=name,
        theme=theme,
        hold_days=hold_days,
        signals=len(returns),
        win_rate=(sum(1 for value in returns if value > 0) / len(returns)) if returns else None,
        avg_return=mean(returns) if returns else None,
        median_return=median(returns) if returns else None,
        best_return=max(returns) if returns else None,
        worst_return=min(returns) if returns else None,
        avg_max_drawdown=mean(drawdowns) if drawdowns else None,
        last_signal_date=last_signal_date,
    )


def _snapshot_passes_current_strength(snapshot: SymbolSnapshot) -> bool:
    return (
        snapshot.status in {"主升确认", "突破观察", "趋势延续"}
        and snapshot.ret_5d is not None
        and BASE_ENTRY_PROFILE["min_ret_5d"] <= snapshot.ret_5d < 0.15
        and snapshot.ret_20d is not None
        and snapshot.ret_20d > 0.03
        and snapshot.amount_ratio is not None
        and snapshot.amount_ratio >= BASE_ENTRY_PROFILE["min_amount_ratio"]
        and snapshot.high_proximity_20d is not None
        and snapshot.high_proximity_20d > BASE_ENTRY_PROFILE["min_high_proximity"]
    )


def _candidate_score(snapshot: SymbolSnapshot, theme: ThemeSnapshot, backtest: BacktestSummary) -> float:
    score = snapshot.score * 0.62 + theme.score * 0.23
    if backtest.win_rate is not None:
        sample_weight = min(1.0, backtest.signals / 5.0)
        score += (backtest.win_rate - 0.5) * 16.0 * sample_weight + 4.0
    if backtest.avg_return is not None:
        sample_weight = min(1.0, backtest.signals / 5.0)
        score += max(-5.0, min(8.0, backtest.avg_return / 0.06 * 8.0)) * sample_weight
    if backtest.signals >= 3:
        score += 3.0
    return round(max(0.0, min(100.0, score)), 2)


def _theme_symbols(theme_config: dict[str, Any], theme_name: str) -> list[str]:
    for theme in theme_config.get("themes", []):
        if str(theme.get("name")) == theme_name:
            return theme_candidate_symbols(theme)
    return []


def fair_select_candidates(
    candidates: list[StrongStockCandidate],
    theme_order: list[str],
    limit: int,
    per_theme_floor: int = 2,
) -> list[StrongStockCandidate]:
    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
    if limit <= 0 or len(ranked) <= limit:
        return ranked

    grouped: dict[str, list[StrongStockCandidate]] = {}
    for candidate in ranked:
        grouped.setdefault(candidate.theme, []).append(candidate)

    selected: list[StrongStockCandidate] = []
    selected_keys: set[tuple[str, str]] = set()
    for theme in theme_order:
        for candidate in grouped.get(theme, [])[:per_theme_floor]:
            if len(selected) >= limit:
                break
            selected.append(candidate)
            selected_keys.add((candidate.theme, candidate.symbol))

    remaining = [candidate for candidate in ranked if (candidate.theme, candidate.symbol) not in selected_keys]
    selected.extend(remaining[: max(0, limit - len(selected))])
    return sorted(selected, key=lambda item: item.score, reverse=True)


def build_strong_stock_report(
    theme_config: dict[str, Any],
    snapshots: dict[str, SymbolSnapshot],
    klines: dict[str, KlineSeries],
    themes: list[ThemeSnapshot],
    hold_days: int = 5,
    max_candidates: int = 12,
    top_theme_count: int = 4,
) -> StrongStockReport:
    active_themes = [theme for theme in themes if theme.status in {"主线成立", "主线候选", "轮动观察"}]
    selected_themes = active_themes[:top_theme_count] if active_themes else themes[: min(top_theme_count, len(themes))]
    candidates: list[StrongStockCandidate] = []
    seen: set[tuple[str, str]] = set()
    for theme in selected_themes:
        for symbol in _theme_symbols(theme_config, theme.name):
            snapshot = snapshots.get(symbol)
            series = klines.get(symbol)
            if not snapshot or not series or not _snapshot_passes_current_strength(snapshot):
                continue
            key = (theme.name, symbol)
            if key in seen:
                continue
            seen.add(key)
            backtest = backtest_symbol(
                symbol=symbol, name=snapshot.name, theme=theme.name, series=series, hold_days=hold_days
            )
            score = _candidate_score(snapshot, theme, backtest)
            candidates.append(
                StrongStockCandidate(
                    symbol=symbol,
                    name=snapshot.name,
                    theme=theme.name,
                    last_close=snapshot.last_close,
                    score=score,
                    status=snapshot.status,
                    ret_5d=snapshot.ret_5d,
                    ret_20d=snapshot.ret_20d,
                    amount_ratio=snapshot.amount_ratio,
                    high_proximity_20d=snapshot.high_proximity_20d,
                    reasons=_candidate_reasons(snapshot, backtest),
                    backtest=backtest,
                )
            )
    theme_order = [theme.name for theme in selected_themes]
    return StrongStockReport(
        selected_themes=theme_order,
        hold_days=hold_days,
        candidates=fair_select_candidates(candidates, theme_order, max_candidates, per_theme_floor=3),
    )
