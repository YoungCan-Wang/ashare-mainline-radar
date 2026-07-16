from __future__ import annotations

from statistics import fmean
from typing import Any

from .market import compute_symbol_snapshot
from .models import (
    AHMomentumPair,
    CrossMarketReport,
    CrossMarketThemeSignal,
    KlineSeries,
    SymbolSnapshot,
    ThemeSnapshot,
)


def cross_market_symbols(theme_config: dict[str, Any]) -> list[str]:
    config = theme_config.get("cross_market") or {}
    symbols: list[str] = []
    for basket in config.get("themes", []):
        symbols.extend(str(symbol) for symbol in basket.get("symbols", []))
    for pair in config.get("ah_pairs", []):
        symbols.append(str(pair.get("h_symbol") or ""))
    return list(dict.fromkeys(symbol for symbol in symbols if symbol))


def cross_market_theme_map(theme_config: dict[str, Any]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for basket in (theme_config.get("cross_market") or {}).get("themes", []):
        name = str(basket["name"])
        for symbol in basket.get("symbols", []):
            mapping.setdefault(str(symbol), []).append(name)
    return mapping


def _average(values: list[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    return fmean(usable) if usable else None


def _with_liquidity_proxy(series: KlineSeries) -> KlineSeries:
    if any(value > 0 for value in series.amount):
        return series
    return KlineSeries(
        symbol=series.symbol,
        timestamp=series.timestamp,
        open=series.open,
        high=series.high,
        low=series.low,
        close=series.close,
        volume=series.volume,
        amount=series.volume,
    )


def _status(a_theme: ThemeSnapshot | None, breadth_5d: float, breadth_20d: float, ret_5d: float) -> str:
    a_active = bool(a_theme and a_theme.status in {"主线成立", "主线候选"})
    hk_active = breadth_5d >= 0.55 and breadth_20d >= 0.50 and ret_5d > 0
    if a_active and hk_active:
        return "A港共振"
    if hk_active:
        return "港股领先"
    if a_active:
        return "A股领先"
    return "A港共同走弱"


def _action(status: str) -> str:
    if status == "A港共振":
        return "跨市场确认增强，但仍服从A股交易闸门和个股触发条件。"
    if status == "港股领先":
        return "观察港股是否带动A股广度扩散；确认前不把映射当成A股买点。"
    if status == "A股领先":
        return "警惕港股未确认或率先转弱；A股新仓降一级处理。"
    return "跨市场均未形成趋势，不参与主题追涨。"


def build_cross_market_report(
    theme_config: dict[str, Any],
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    a_themes: list[ThemeSnapshot],
    a_snapshots: dict[str, SymbolSnapshot],
) -> CrossMarketReport:
    config = theme_config.get("cross_market") or {}
    theme_map = cross_market_theme_map(theme_config)
    snapshots: dict[str, SymbolSnapshot] = {}
    for symbol, series in klines.items():
        snapshot = compute_symbol_snapshot(
            symbol,
            _with_liquidity_proxy(series),
            instruments.get(symbol),
            theme_map.get(symbol, []),
        )
        if snapshot:
            snapshots[symbol] = snapshot

    a_theme_by_name = {theme.name: theme for theme in a_themes}
    a_rank = {theme.name: rank for rank, theme in enumerate(a_themes, start=1)}
    signals: list[CrossMarketThemeSignal] = []
    for basket in config.get("themes", []):
        name = str(basket["name"])
        members = [snapshots[str(symbol)] for symbol in basket.get("symbols", []) if str(symbol) in snapshots]
        if not members:
            continue
        breadth_5d = sum((item.ret_5d or 0) > 0 for item in members) / len(members)
        breadth_20d = sum((item.ret_20d or 0) > 0 for item in members) / len(members)
        avg_ret_5d = _average([item.ret_5d for item in members]) or 0.0
        avg_ret_20d = _average([item.ret_20d for item in members]) or 0.0
        amount_heat = _average([item.amount_ratio for item in members])
        status = _status(a_theme_by_name.get(name), breadth_5d, breadth_20d, avg_ret_5d)
        score = min(
            100.0,
            max(
                0.0,
                35 + breadth_5d * 20 + breadth_20d * 20 + avg_ret_5d / 0.10 * 15 + avg_ret_20d / 0.25 * 10,
            ),
        )
        signals.append(
            CrossMarketThemeSignal(
                theme=name,
                status=status,
                score=round(score, 2),
                hk_members=len(members),
                hk_breadth_5d=breadth_5d,
                hk_breadth_20d=breadth_20d,
                hk_avg_ret_5d=avg_ret_5d,
                hk_avg_ret_20d=avg_ret_20d,
                hk_amount_heat=amount_heat,
                a_share_rank=a_rank.get(name),
                a_share_status=a_theme_by_name[name].status if name in a_theme_by_name else None,
                action=_action(status),
                leaders=sorted(members, key=lambda item: item.score, reverse=True)[:5],
                evidence=[
                    f"港股5日上涨 {sum((item.ret_5d or 0) > 0 for item in members)}/{len(members)}",
                    f"港股20日上涨 {sum((item.ret_20d or 0) > 0 for item in members)}/{len(members)}",
                ],
            )
        )

    pairs: list[AHMomentumPair] = []
    for pair in config.get("ah_pairs", []):
        a_symbol = str(pair["a_symbol"])
        h_symbol = str(pair["h_symbol"])
        a_snapshot = a_snapshots.get(a_symbol)
        h_snapshot = snapshots.get(h_symbol)
        if a_snapshot is None or h_snapshot is None:
            continue
        spread = (
            h_snapshot.ret_5d - a_snapshot.ret_5d
            if h_snapshot.ret_5d is not None and a_snapshot.ret_5d is not None
            else None
        )
        leader = "同步"
        if spread is not None and spread >= 0.02:
            leader = "H股领先"
        elif spread is not None and spread <= -0.02:
            leader = "A股领先"
        pairs.append(
            AHMomentumPair(
                company=str(pair["company"]),
                a_symbol=a_symbol,
                h_symbol=h_symbol,
                a_ret_5d=a_snapshot.ret_5d,
                h_ret_5d=h_snapshot.ret_5d,
                a_ret_20d=a_snapshot.ret_20d,
                h_ret_20d=h_snapshot.ret_20d,
                leader=leader,
                spread_5d=spread,
            )
        )

    signals.sort(key=lambda item: (item.a_share_rank is not None, item.score), reverse=True)
    return CrossMarketReport(
        themes=signals,
        ah_pairs=pairs,
        notes=[
            "跨市场状态仅作确认/否决证据，尚未通过样本外检验前不直接提高买入分数。",
            "A/H配对只比较复权收益动量；未接入实时汇率和股本换算前不计算A/H溢价。",
            "港股篮子使用可经港股通交易的恒生生物科技核心成分，不代表全部港股通证券。",
        ],
    )
