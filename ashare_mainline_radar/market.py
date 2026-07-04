from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from .models import KlineSeries, SymbolSnapshot, ThemeSnapshot, safe_change


def _avg(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None]
    return mean(clean) if clean else None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _score_change(value: float | None, scale: float, neutral: float = 0.0) -> float:
    if value is None:
        return 0.0
    return _clip((value - neutral) / scale, -1.0, 1.5)


def classify_symbol(ret_5d: float | None, ret_20d: float | None, amount_ratio: float | None, high_proximity: float | None) -> str:
    if ret_20d is not None and ret_20d > 0.12 and amount_ratio is not None and amount_ratio > 1.25:
        return "主升确认"
    if ret_5d is not None and ret_5d > 0.04 and high_proximity is not None and high_proximity > -0.04:
        return "突破观察"
    if ret_20d is not None and ret_20d > 0 and amount_ratio is not None and amount_ratio > 0.9:
        return "趋势延续"
    if ret_5d is not None and ret_5d < -0.05:
        return "短线降温"
    return "中性"


def compute_symbol_snapshot(
    symbol: str,
    series: KlineSeries,
    instrument: dict[str, Any] | None = None,
    themes: list[str] | None = None,
) -> SymbolSnapshot | None:
    if not series.usable:
        return None
    close = series.close
    high = series.high
    amount = series.amount
    last_close = close[-1]
    ret_1d = safe_change(close[-1], close[-2]) if len(close) >= 2 else None
    ret_5d = safe_change(close[-1], close[-6]) if len(close) >= 6 else None
    ret_20d = safe_change(close[-1], close[-21]) if len(close) >= 21 else None
    amount_ma5 = _avg(amount[-5:])
    amount_ma20 = _avg(amount[-20:])
    amount_ratio = (amount_ma5 / amount_ma20) if amount_ma5 is not None and amount_ma20 else None
    high_20d = max(high[-20:])
    high_proximity_20d = safe_change(last_close, high_20d)
    drawdown_20d = high_proximity_20d

    score = 50.0
    score += 18.0 * _score_change(ret_20d, 0.20)
    score += 14.0 * _score_change(ret_5d, 0.10)
    score += 10.0 * _score_change(ret_1d, 0.05)
    if amount_ratio is not None:
        score += 12.0 * _clip(amount_ratio - 1.0, -0.8, 1.5)
    if high_proximity_20d is not None:
        score += 8.0 * _clip(1.0 + high_proximity_20d / 0.08, -1.0, 1.0)
    score = round(_clip(score, 0.0, 100.0), 2)

    name = symbol
    if instrument:
        name = str(instrument.get("name") or symbol)

    return SymbolSnapshot(
        symbol=symbol,
        name=name,
        themes=themes or [],
        last_close=last_close,
        ret_1d=ret_1d,
        ret_5d=ret_5d,
        ret_20d=ret_20d,
        amount_ma5=amount_ma5,
        amount_ma20=amount_ma20,
        amount_ratio=amount_ratio,
        high_proximity_20d=high_proximity_20d,
        drawdown_20d=drawdown_20d,
        score=score,
        status=classify_symbol(ret_5d, ret_20d, amount_ratio, high_proximity_20d),
    )


def classify_theme(score: float, breadth_20d: float | None, amount_heat: float | None) -> str:
    if score >= 78 and breadth_20d is not None and breadth_20d >= 0.58:
        return "主线成立"
    if score >= 68 and amount_heat is not None and amount_heat >= 1.05:
        return "主线候选"
    if score >= 58:
        return "轮动观察"
    return "弱势/等待"


def build_theme_snapshots(
    theme_config: dict[str, Any],
    snapshots: dict[str, SymbolSnapshot],
    catalysts_by_theme: dict[str, int] | None = None,
    policy_counts_by_theme: dict[str, int] | None = None,
    policy_scores_by_theme: dict[str, float] | None = None,
) -> list[ThemeSnapshot]:
    catalysts_by_theme = catalysts_by_theme or {}
    policy_counts_by_theme = policy_counts_by_theme or {}
    policy_scores_by_theme = policy_scores_by_theme or {}
    result: list[ThemeSnapshot] = []
    for theme in theme_config.get("themes", []):
        name = str(theme["name"])
        symbols = list(dict.fromkeys([*theme.get("symbols", []), *theme.get("vehicles", [])]))
        members = [snapshots[symbol] for symbol in symbols if symbol in snapshots]
        if not members:
            continue
        positive_5d = [member for member in members if member.ret_5d is not None and member.ret_5d > 0]
        positive_20d = [member for member in members if member.ret_20d is not None and member.ret_20d > 0]
        breadth_5d = len(positive_5d) / len(members)
        breadth_20d = len(positive_20d) / len(members)
        avg_ret_5d = _avg([member.ret_5d for member in members if member.ret_5d is not None])
        avg_ret_20d = _avg([member.ret_20d for member in members if member.ret_20d is not None])
        amount_heat = _avg([member.amount_ratio for member in members if member.amount_ratio is not None])
        leaders = sorted(members, key=lambda item: item.score, reverse=True)[:5]
        catalyst_count = catalysts_by_theme.get(name, 0)
        policy_count = policy_counts_by_theme.get(name, 0)
        policy_score = policy_scores_by_theme.get(name, 0.0)

        score = 45.0
        score += 20.0 * (breadth_20d or 0.0)
        score += 12.0 * (breadth_5d or 0.0)
        score += 14.0 * _score_change(avg_ret_20d, 0.16)
        score += 8.0 * _score_change(avg_ret_5d, 0.08)
        if amount_heat is not None:
            score += 10.0 * _clip(amount_heat - 1.0, -0.8, 1.4)
        score += min(6.0, catalyst_count * 1.2)
        score += min(8.0, policy_score * 0.08)
        score += _clip((mean([leader.score for leader in leaders[:3]]) - 60.0) / 10.0, -4.0, 6.0) if leaders else 0.0
        score = round(_clip(score, 0.0, 100.0), 2)

        evidence = [
            f"20日上涨成员 {len(positive_20d)}/{len(members)}",
            f"5日上涨成员 {len(positive_5d)}/{len(members)}",
        ]
        if amount_heat is not None:
            evidence.append(f"成交热度 {amount_heat:.2f}x")
        if catalyst_count:
            evidence.append(f"命中情报线索 {catalyst_count} 条")
        if policy_count:
            evidence.append(f"政策催化 {policy_count} 条，政策分 {policy_score:.1f}")

        result.append(
            ThemeSnapshot(
                name=name,
                score=score,
                status=classify_theme(score, breadth_20d, amount_heat),
                members=len(members),
                breadth_5d=breadth_5d,
                breadth_20d=breadth_20d,
                avg_ret_5d=avg_ret_5d,
                avg_ret_20d=avg_ret_20d,
                amount_heat=amount_heat,
                catalyst_count=catalyst_count,
                leaders=leaders,
                policy_catalyst_count=policy_count,
                policy_score=policy_score,
                vehicles=list(theme.get("vehicles", [])),
                evidence=evidence,
            )
        )
    return sorted(result, key=lambda item: item.score, reverse=True)


def build_leader_tape(snapshots: dict[str, SymbolSnapshot], limit: int = 25) -> list[SymbolSnapshot]:
    return sorted(snapshots.values(), key=lambda item: item.score, reverse=True)[:limit]


def catalyst_counts(intel_matches: dict[str, list[str]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for themes in intel_matches.values():
        for theme in themes:
            counts[theme] += 1
    return dict(counts)
