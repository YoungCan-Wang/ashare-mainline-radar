from __future__ import annotations

from statistics import mean
from typing import Any

from .models import MarketPulse, SymbolSnapshot


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _pulse_status(score: float, avg_ret_20d: float | None, positive_20d: float | None) -> str:
    if score >= 72 and avg_ret_20d is not None and avg_ret_20d > 0:
        return "风险偏好转强"
    if score >= 60 and positive_20d is not None and positive_20d >= 0.5:
        return "结构性友好"
    if score >= 46:
        return "中性震荡"
    return "风险收缩"


def build_market_pulses(theme_config: dict[str, Any], snapshots: dict[str, SymbolSnapshot]) -> list[MarketPulse]:
    groups = theme_config.get("market_context_groups") or []
    pulses: list[MarketPulse] = []
    for group in groups:
        name = str(group["name"])
        symbols = [str(symbol) for symbol in group.get("symbols", [])]
        members = [snapshots[symbol] for symbol in symbols if symbol in snapshots]
        if not members:
            continue

        avg_ret_5d = _avg([item.ret_5d for item in members if item.ret_5d is not None])
        avg_ret_20d = _avg([item.ret_20d for item in members if item.ret_20d is not None])
        amount_heat = _avg([item.amount_ratio for item in members if item.amount_ratio is not None])
        positives = [item for item in members if item.ret_20d is not None and item.ret_20d > 0]
        positive_20d = len(positives) / len(members)

        score = 50.0
        if avg_ret_20d is not None:
            score += 22.0 * _clip(avg_ret_20d / 0.10, -1.0, 1.4)
        if avg_ret_5d is not None:
            score += 14.0 * _clip(avg_ret_5d / 0.05, -1.0, 1.4)
        if amount_heat is not None:
            score += 10.0 * _clip(amount_heat - 1.0, -0.8, 1.5)
        score += 12.0 * (positive_20d - 0.5)
        score = round(_clip(score, 0.0, 100.0), 2)

        leaders = sorted(members, key=lambda item: item.score, reverse=True)[:4]
        evidence = [
            f"20日上涨成员 {len(positives)}/{len(members)}",
        ]
        if avg_ret_5d is not None:
            evidence.append(f"5日均涨幅 {avg_ret_5d * 100:.2f}%")
        if avg_ret_20d is not None:
            evidence.append(f"20日均涨幅 {avg_ret_20d * 100:.2f}%")
        if amount_heat is not None:
            evidence.append(f"成交热度 {amount_heat:.2f}x")

        pulses.append(
            MarketPulse(
                name=name,
                status=_pulse_status(score, avg_ret_20d, positive_20d),
                score=score,
                members=len(members),
                avg_ret_5d=avg_ret_5d,
                avg_ret_20d=avg_ret_20d,
                amount_heat=amount_heat,
                positive_20d=positive_20d,
                leaders=leaders,
                evidence=evidence,
            )
        )
    return sorted(pulses, key=lambda item: item.score, reverse=True)
