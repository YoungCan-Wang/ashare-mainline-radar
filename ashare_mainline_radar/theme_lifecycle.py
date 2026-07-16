from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .config import theme_scoring_symbols, theme_symbol_map
from .market import build_theme_snapshots, compute_symbol_snapshot
from .models import (
    KlineSeries,
    SymbolSnapshot,
    ThemeLifecycleReport,
    ThemeLifecycleSignal,
    ThemeSnapshot,
    cn_market_date_from_ms,
    pct,
)

STAGE_PRIORITY = {
    "扩散启动": 6,
    "主线确认": 5,
    "主升加速": 4,
    "主线回踩": 3,
    "主线延续": 2,
    "退潮预警": 1,
    "资金试探": 0,
    "弱势等待": -1,
}


@dataclass(frozen=True)
class LifecyclePoint:
    date: str
    status: str
    score: float
    breadth_5d: float | None
    breadth_20d: float | None
    avg_ret_5d: float | None
    avg_ret_20d: float | None
    amount_heat: float | None


def _value(value: float | None) -> float:
    return value if value is not None else 0.0


def _raw_stage(point: LifecyclePoint) -> str:
    breadth_5d = _value(point.breadth_5d)
    breadth_20d = _value(point.breadth_20d)
    avg_ret_5d = _value(point.avg_ret_5d)
    avg_ret_20d = _value(point.avg_ret_20d)
    amount_heat = _value(point.amount_heat)
    if (
        breadth_5d >= 0.72
        and breadth_20d >= 0.58
        and avg_ret_5d >= 0.05
        and avg_ret_20d >= 0.03
        and amount_heat >= 1.08
    ):
        return "主升加速"
    if point.status == "主线成立" and (breadth_5d < 0.45 or avg_ret_5d <= 0):
        return "回踩态"
    if point.status == "主线成立" and avg_ret_20d > 0:
        return "主线确认"
    if breadth_5d >= 0.60 and avg_ret_5d >= 0.015 and amount_heat >= 1.03:
        return "扩散启动"
    if breadth_5d >= 0.50 and avg_ret_5d > 0 and amount_heat >= 1.0:
        return "资金试探"
    return "弱势等待"


def _action(stage: str) -> str:
    actions = {
        "扩散启动": "加入重点观察，等待核心股同步转强和20日广度确认；不要把启动预警当成开盘买入指令。",
        "主线确认": "主线已完成广度确认，优先等待核心股回踩企稳或放量突破后分批参与。",
        "主线延续": "主线结构仍在，已有仓位按失效位持有，新仓只等回踩或二次放量。",
        "主升加速": "板块进入加速段，不追一致性高开，只参与缩量回踩后的再次转强。",
        "主线回踩": "保留主线身份并等待止跌确认；单日降温不直接判定退潮，也不在下跌中补仓。",
        "退潮预警": "停止新增仓位，检查核心股、20日广度和成交热度是否继续恶化。",
        "资金试探": "资金开始试探但尚未形成扩散，只进入观察池。",
        "弱势等待": "当前没有形成可跟踪的主线生命周期信号。",
    }
    return actions[stage]


def trace_theme_lifecycle(
    theme: str,
    points: list[LifecyclePoint],
    current_theme: ThemeSnapshot,
) -> ThemeLifecycleSignal | None:
    if not points:
        return None

    active = False
    started_at: str | None = None
    confirmed_at: str | None = None
    stage = "弱势等待"
    stage_since = points[0].date
    previous_stage: str | None = None
    weak_streak = 0
    transition_index = 0

    for index, point in enumerate(points):
        raw_stage = _raw_stage(point)
        next_stage = stage
        if not active:
            if raw_stage in {"扩散启动", "主线确认", "主升加速"}:
                active = True
                started_at = point.date
                next_stage = raw_stage
                if raw_stage in {"主线确认", "主升加速"}:
                    confirmed_at = point.date
            else:
                next_stage = "资金试探" if raw_stage == "资金试探" else "弱势等待"
        else:
            if raw_stage == "主升加速":
                weak_streak = 0
                confirmed_at = confirmed_at or point.date
                next_stage = "主升加速"
            elif raw_stage == "主线确认":
                weak_streak = 0
                confirmed_at = confirmed_at or point.date
                next_stage = "主线确认" if confirmed_at == point.date else "主线延续"
            elif raw_stage == "回踩态":
                weak_streak += 1
                if confirmed_at and weak_streak <= 5:
                    next_stage = "主线回踩"
                elif confirmed_at and weak_streak <= 7:
                    next_stage = "退潮预警"
                else:
                    active = False
                    started_at = None
                    confirmed_at = None
                    next_stage = "弱势等待"
            elif raw_stage in {"扩散启动", "资金试探"}:
                weak_streak = 0
                if confirmed_at:
                    cooling = _value(point.avg_ret_5d) <= 0 or _value(point.breadth_5d) < 0.50
                    next_stage = "主线回踩" if cooling else "主线延续"
                else:
                    next_stage = "扩散启动"
            else:
                weak_streak += 1
                breadth_20d = _value(point.breadth_20d)
                avg_ret_20d = _value(point.avg_ret_20d)
                if confirmed_at and breadth_20d >= 0.58 and avg_ret_20d > 0 and weak_streak <= 5:
                    next_stage = "主线回踩"
                elif confirmed_at and weak_streak <= 2:
                    next_stage = "退潮预警"
                elif weak_streak >= 3:
                    active = False
                    started_at = None
                    confirmed_at = None
                    next_stage = "弱势等待"
                else:
                    next_stage = "退潮预警"

        if next_stage != stage:
            previous_stage = stage
            stage = next_stage
            stage_since = point.date
            transition_index = index

    latest = points[-1]
    if stage == "弱势等待":
        return None
    evidence = [
        f"5日广度 {pct(latest.breadth_5d)}",
        f"20日广度 {pct(latest.breadth_20d)}",
        f"5日均涨幅 {pct(latest.avg_ret_5d)}",
        f"成交热度 {_value(latest.amount_heat):.2f}x",
    ]
    return ThemeLifecycleSignal(
        theme=theme,
        stage=stage,
        score=current_theme.score,
        current_status=current_theme.status,
        started_at=started_at,
        confirmed_at=confirmed_at,
        stage_since=stage_since,
        previous_stage=previous_stage,
        transition_age=len(points) - 1 - transition_index,
        breadth_5d=latest.breadth_5d,
        breadth_20d=latest.breadth_20d,
        avg_ret_5d=latest.avg_ret_5d,
        avg_ret_20d=latest.avg_ret_20d,
        amount_heat=latest.amount_heat,
        action=_action(stage),
        evidence=evidence,
    )


def _slice_series(series: KlineSeries, cutoff: int) -> KlineSeries | None:
    end = bisect_right(series.timestamp, cutoff)
    if end < 21:
        return None
    return KlineSeries(
        symbol=series.symbol,
        timestamp=series.timestamp[:end],
        open=series.open[:end],
        high=series.high[:end],
        low=series.low[:end],
        close=series.close[:end],
        volume=series.volume[:end],
        amount=series.amount[:end],
    )


def _history_cutoffs(klines: dict[str, KlineSeries], history_days: int) -> list[int]:
    counts = Counter(timestamp for series in klines.values() for timestamp in series.timestamp)
    if not counts:
        return []
    minimum_coverage = max(3, int(len(klines) * 0.35))
    cutoffs = sorted(timestamp for timestamp, count in counts.items() if count >= minimum_coverage)
    return cutoffs[-history_days:]


def build_theme_lifecycle_report(
    theme_config: dict[str, Any],
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    current_themes: list[ThemeSnapshot],
    history_days: int = 45,
) -> ThemeLifecycleReport:
    scoring_symbols = {symbol for theme in theme_config.get("themes", []) for symbol in theme_scoring_symbols(theme)}
    relevant_klines = {symbol: series for symbol, series in klines.items() if symbol in scoring_symbols}
    cutoffs = _history_cutoffs(relevant_klines, history_days)
    if not cutoffs:
        return ThemeLifecycleReport(signals=[], history_days=0, notes=["历史日K不足，无法回放主线生命周期。"])

    symbol_to_themes = theme_symbol_map(theme_config)
    history: dict[str, list[LifecyclePoint]] = {str(theme["name"]): [] for theme in theme_config.get("themes", [])}
    for cutoff in cutoffs:
        snapshots: dict[str, SymbolSnapshot] = {}
        for symbol, series in relevant_klines.items():
            sliced = _slice_series(series, cutoff)
            if sliced is None:
                continue
            snapshot = compute_symbol_snapshot(
                symbol=symbol,
                series=sliced,
                instrument=instruments.get(symbol),
                themes=symbol_to_themes.get(symbol, []),
            )
            if snapshot:
                snapshots[symbol] = snapshot
        date = cn_market_date_from_ms(cutoff)
        if date is None:
            continue
        for theme in build_theme_snapshots(theme_config, snapshots):
            if theme.members < 4:
                continue
            history[theme.name].append(
                LifecyclePoint(
                    date=date,
                    status=theme.status,
                    score=theme.score,
                    breadth_5d=theme.breadth_5d,
                    breadth_20d=theme.breadth_20d,
                    avg_ret_5d=theme.avg_ret_5d,
                    avg_ret_20d=theme.avg_ret_20d,
                    amount_heat=theme.amount_heat,
                )
            )

    current_by_name = {theme.name: theme for theme in current_themes}
    signals = [
        signal
        for name, points in history.items()
        if (current_theme := current_by_name.get(name))
        and (signal := trace_theme_lifecycle(name, points, current_theme))
    ]
    signals.sort(
        key=lambda signal: (
            signal.is_new_transition,
            STAGE_PRIORITY.get(signal.stage, -2),
            signal.score,
        ),
        reverse=True,
    )
    notes = [
        "生命周期使用历史日K回放，政策和新闻只作为当日增强，不反向写入历史价格状态。",
        "市场风险闸门只约束是否参与，不会隐藏扩散启动、主线回踩或退潮预警。",
    ]
    return ThemeLifecycleReport(signals=signals, history_days=len(cutoffs), notes=notes)
