from __future__ import annotations

from typing import Any

from .models import SymbolSnapshot, UnmappedStrengthReport


def _company_symbol(snapshot: SymbolSnapshot, instrument: dict[str, Any] | None) -> bool:
    if not snapshot.symbol.endswith((".SH", ".SZ", ".BJ")):
        return False
    name = str((instrument or {}).get("name") or snapshot.name).upper()
    return not any(token in name for token in ("ETF", "LOF", "REIT", "指数", "基金", "转债"))


def build_unmapped_strength_report(
    snapshots: dict[str, SymbolSnapshot],
    instruments: dict[str, dict[str, Any]],
    mode: str,
    limit: int = 20,
) -> UnmappedStrengthReport:
    unmapped = [
        item
        for item in snapshots.values()
        if not item.themes and _company_symbol(item, instruments.get(item.symbol))
    ]
    candidates = [
        item
        for item in unmapped
        if (item.relative_percentile or 0.0) >= 80.0
        and item.ret_5d is not None
        and item.ret_5d > 0.02
        and item.ret_20d is not None
        and item.ret_20d > 0.05
        and item.amount_ratio is not None
        and item.amount_ratio >= 1.0
        and item.high_proximity_20d is not None
        and item.high_proximity_20d > -0.08
    ]
    candidates.sort(key=lambda item: (item.relative_percentile or 0.0, item.score), reverse=True)
    notes = [
        "未映射池只负责发现预设主题之外的强势个股，不自动把同涨误判成产业主线。",
        "候选需满足横截面前20%、5/20日上涨、成交不缩量且距离20日高点不超过8%。",
    ]
    if mode != "universe":
        notes.append("当前不是全市场模式，未映射发现只覆盖本次已请求标的；请用 universe 模式完成全市场发现。")
    return UnmappedStrengthReport(
        candidates=candidates[:limit],
        scanned_unmapped=len(unmapped),
        notes=notes,
    )
