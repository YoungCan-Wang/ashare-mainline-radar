from __future__ import annotations

from statistics import median
from typing import Any

from .models import MarketPulse, MarketStructure, SymbolSnapshot, TradingGate


def _broad_symbols(theme_config: dict[str, Any]) -> list[str]:
    for group in theme_config.get("market_context_groups", []):
        if group.get("name") == "A股宽基环境":
            return [str(symbol) for symbol in group.get("symbols", [])]
    return []


def _stock_like(snapshot: SymbolSnapshot, index_symbols: set[str]) -> bool:
    if snapshot.symbol in index_symbols or not snapshot.symbol.endswith((".SH", ".SZ")):
        return False
    upper = snapshot.name.upper()
    return not any(token in upper for token in ("ETF", "LOF", "REIT", "指数", "基金", "转债", "退"))


def _hard_risk_trigger(
    *,
    market_structure: MarketStructure | None,
    systemic_selloff: bool,
    index_stress: bool,
    breadth_confirms_stress: bool,
) -> str:
    """把真正触发硬熔断的路径写成首条理由，方便飞书卡片一眼看懂。"""
    if market_structure and market_structure.status == "破位确认":
        ratio = market_structure.confirmed_breakdown_ratio
        ratio_text = f"，连续3日跌破20日线指数 {ratio * 100:.0f}%" if ratio is not None else ""
        return f"硬熔断：指数结构破位确认{ratio_text}；个股反弹再猛也不新开仓，直到多数指数收复20日线"
    if systemic_selloff:
        return "硬熔断：系统性杀跌（上涨占比过低且跌超2%占比过高）"
    if index_stress and breadth_confirms_stress:
        return "硬熔断：指数压力叠加个股广度恶化"
    return "硬熔断：市场风险闸门触发"


def build_trading_gate(
    theme_config: dict[str, Any],
    snapshots: dict[str, SymbolSnapshot],
    market_pulses: list[MarketPulse],
    market_structure: MarketStructure | None = None,
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
    index_symbol_set = set(index_symbols)
    stock_returns = [
        snapshot.ret_1d
        for snapshot in snapshots.values()
        if _stock_like(snapshot, index_symbol_set) and snapshot.ret_1d is not None
    ]
    stock_returns_5d = [
        snapshot.ret_5d
        for snapshot in snapshots.values()
        if _stock_like(snapshot, index_symbol_set) and snapshot.ret_5d is not None
    ]
    advance_ratio = sum(value > 0 for value in stock_returns) / len(stock_returns) if stock_returns else None
    decline_2pct_ratio = sum(value <= -0.02 for value in stock_returns) / len(stock_returns) if stock_returns else None
    median_stock_return = median(stock_returns) if stock_returns else None
    median_stock_return_5d = median(stock_returns_5d) if stock_returns_5d else None
    reasons: list[str] = []
    if median_1d is not None:
        reasons.append(f"三大指数单日中位涨跌 {median_1d * 100:.2f}%")
    if broad:
        reasons.append(f"A股宽基环境 {broad.status}，强度 {broad.score:.1f}")
    if market_structure:
        reasons.append(f"指数结构 {market_structure.status}，确认分 {market_structure.score:.1f}")
    if advance_ratio is not None and decline_2pct_ratio is not None:
        reasons.append(f"扫描股票上涨占比 {advance_ratio * 100:.1f}%，跌超2%占比 {decline_2pct_ratio * 100:.1f}%")

    index_stress = bool(
        crash_count >= 2
        or (median_1d is not None and median_1d <= -0.02)
        or (broad and broad.status == "风险收缩" and broad.score < 40)
    )
    breadth_confirms_stress = bool(
        advance_ratio is None
        or advance_ratio <= 0.35
        or (decline_2pct_ratio is not None and decline_2pct_ratio >= 0.35)
    )
    systemic_selloff = bool(
        advance_ratio is not None
        and decline_2pct_ratio is not None
        and advance_ratio <= 0.20
        and decline_2pct_ratio >= 0.40
    )

    hard_risk = bool(
        (index_stress and breadth_confirms_stress)
        or systemic_selloff
        or (market_structure and market_structure.status == "破位确认")
    )
    if hard_risk:
        trigger = _hard_risk_trigger(
            market_structure=market_structure,
            systemic_selloff=systemic_selloff,
            index_stress=index_stress,
            breadth_confirms_stress=breadth_confirms_stress,
        )
        return TradingGate(
            level="red",
            state="暂停新仓",
            score=round(broad.score if broad else 20.0, 2),
            max_initial_position_fraction=0.0,
            reasons=[trigger, *reasons],
            allowed_actions=["管理已有仓位", "执行减仓/退出纪律", "观察黄金坑确认信号"],
            advance_ratio=advance_ratio,
            decline_2pct_ratio=decline_2pct_ratio,
            median_stock_return=median_stock_return,
            median_stock_return_5d=median_stock_return_5d,
        )

    cautious = bool(
        not broad
        or broad.score < 55
        or broad.status in {"风险收缩", "中性震荡"}
        or (median_1d is not None and median_1d <= -0.01)
        or index_stress
        or (advance_ratio is not None and advance_ratio < 0.48)
        or (market_structure and market_structure.status in {"结构数据不足", "破位观察", "底部未确认", "筑底观察"})
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
            advance_ratio=advance_ratio,
            decline_2pct_ratio=decline_2pct_ratio,
            median_stock_return=median_stock_return,
            median_stock_return_5d=median_stock_return_5d,
        )

    return TradingGate(
        level="green",
        state="允许寻找买点",
        score=round(broad.score, 2),
        max_initial_position_fraction=1 / 3,
        reasons=reasons,
        allowed_actions=["按触发条件分批", "首笔不超过计划仓位1/3", "失效时退出"],
        advance_ratio=advance_ratio,
        decline_2pct_ratio=decline_2pct_ratio,
        median_stock_return=median_stock_return,
        median_stock_return_5d=median_stock_return_5d,
    )
