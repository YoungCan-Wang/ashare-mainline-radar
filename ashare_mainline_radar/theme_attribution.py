from __future__ import annotations

from typing import Any

from .config import theme_keywords, theme_scoring_symbols
from .models import SymbolSnapshot, ThemeAttributionSuggestion, ThemeSnapshot


def _name_keyword_hits(name: str, keywords: list[str]) -> list[str]:
    hits: list[str] = []
    for keyword in keywords:
        token = str(keyword).strip()
        if token and token in name:
            hits.append(token)
    return hits


def suggest_theme_attribution(
    snapshot: SymbolSnapshot,
    theme_config: dict[str, Any],
    themes: list[ThemeSnapshot] | None = None,
    max_suggestions: int = 1,
) -> list[ThemeAttributionSuggestion]:
    """Suggest theme membership for unmapped strong names via keyword + return proximity."""
    if snapshot.themes:
        return []
    keywords_by_theme = theme_keywords(theme_config)
    theme_by_name = {theme.name: theme for theme in themes or []}
    scored: list[ThemeAttributionSuggestion] = []
    for theme_cfg in theme_config.get("themes", []):
        theme_name = str(theme_cfg.get("name") or "")
        if not theme_name:
            continue
        hits = _name_keyword_hits(snapshot.name, keywords_by_theme.get(theme_name, []))
        evidence: list[str] = []
        confidence = 0.0
        method = "none"
        if hits:
            confidence = min(0.85, 0.45 + 0.12 * len(hits))
            method = "keyword"
            evidence.append(f"名称命中关键词：{'、'.join(hits[:4])}")
        theme_snap = theme_by_name.get(theme_name)
        if (
            theme_snap
            and snapshot.ret_5d is not None
            and theme_snap.avg_ret_5d is not None
            and snapshot.ret_20d is not None
            and theme_snap.avg_ret_20d is not None
        ):
            gap_5 = abs(snapshot.ret_5d - theme_snap.avg_ret_5d)
            gap_20 = abs(snapshot.ret_20d - theme_snap.avg_ret_20d)
            if gap_5 <= 0.04 and gap_20 <= 0.08 and theme_snap.status in {"主线成立", "主线候选", "轮动观察"}:
                proximity = 0.35 + max(0.0, 0.25 - gap_5 * 4) + max(0.0, 0.15 - gap_20)
                if proximity > confidence:
                    confidence = min(0.8, proximity)
                    method = "return_proximity" if method == "none" else "keyword+return"
                evidence.append(
                    f"近5/20日涨幅贴近主题均值（Δ5日 {gap_5 * 100:.1f}pp，Δ20日 {gap_20 * 100:.1f}pp）"
                )
        leaders = theme_scoring_symbols(theme_cfg)[:3]
        if leaders and snapshot.symbol in leaders:
            confidence = max(confidence, 0.9)
            method = "basket_member"
            evidence.append("已在主题评分池中但快照 themes 为空")
        if confidence >= 0.45:
            scored.append(
                ThemeAttributionSuggestion(
                    symbol=snapshot.symbol,
                    name=snapshot.name,
                    suggested_theme=theme_name,
                    confidence=round(confidence, 3),
                    method=method,
                    evidence=evidence or ["弱匹配"],
                )
            )
    scored.sort(key=lambda item: item.confidence, reverse=True)
    return scored[:max_suggestions]


def suggest_unmapped_attributions(
    leader_tape: list[SymbolSnapshot],
    theme_config: dict[str, Any],
    themes: list[ThemeSnapshot],
    limit: int = 12,
) -> list[ThemeAttributionSuggestion]:
    suggestions: list[ThemeAttributionSuggestion] = []
    for snapshot in leader_tape:
        if snapshot.themes:
            continue
        suggestions.extend(suggest_theme_attribution(snapshot, theme_config, themes, max_suggestions=1))
        if len(suggestions) >= limit:
            break
    return suggestions[:limit]
