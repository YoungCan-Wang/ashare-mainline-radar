from __future__ import annotations

from statistics import median
from typing import Any

from .models import MarketPulse, SymbolSnapshot, TradingGate


def _broad_symbols(theme_config: dict[str, Any]) -> list[str]:
    for group in theme_config.get("market_context_groups", []):
        if group.get("name") == "A股宽基环境":
            return [str(symbol) for symbol in group.get("symbols", [])]
    return []


def build_trading_gate(
    theme_config: dict[str, Any],
    snapshots: dict[str, SymbolSnapshot],
    market_pulses: list[MarketPulse],
) -> TradingGate:
    broad = next((pulse for pulse in market_pulses if pulse.name == "A股宽基环境"), None)
    index_symbols = _broad_symbols(theme_config)[:3]
    daily_returns = [
        snapshots[symbol].ret_1d
        for symbol in index_symbols
        if symbol in snapshots and snapshots[symbol].ret_1d is not None
    ]
    median_1d = median(daily_returns) if daily_returns else None
    crash_count = sum(value <= -0.02 for value in daily_returns)
    reasons: list[str] = []
    if median_1d is not None:
        reasons.append(f"三大指数单日中位涨跌 {median_1d * 100:.2f}%")
    if broad:
        reasons.append(f"A股宽基环境 {broad.status}，强度 {broad.score:.1f}")

    hard_risk = bool(
        crash_count >= 2
        or (median_1d is not None and median_1d <= -0.02)
        or (broad and broad.status == "风险收缩" and broad.score < 40)
    )
    if hard_risk:
        return TradingGate(
            level="red",
            state="暂停新仓",
            score=round(broad.score if broad else 20.0, 2),
            max_initial_position_fraction=0.0,
            reasons=reasons,
            allowed_actions=["管理已有仓位", "执行减仓/退出纪律", "观察黄金坑确认信号"],
        )

    cautious = bool(
        not broad
        or broad.score < 55
        or broad.status in {"风险收缩", "中性震荡"}
        or (median_1d is not None and median_1d <= -0.01)
    )
    if cautious:
        if not reasons:
            reasons.append("A股宽基数据不足，按谨慎状态处理")
        return TradingGate(
            level="orange",
            state="只准试错仓",
            score=round(broad.score if broad else 45.0, 2),
            max_initial_position_fraction=1 / 3,
            reasons=reasons,
            allowed_actions=["等待触发后小仓试错", "不追高", "确认后再加仓"],
        )

    return TradingGate(
        level="green",
        state="允许寻找买点",
        score=round(broad.score, 2),
        max_initial_position_fraction=1 / 3,
        reasons=reasons,
        allowed_actions=["按触发条件分批", "首笔不超过计划仓位1/3", "失效时退出"],
    )
