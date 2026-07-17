from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from .models import IntelItem, PolicySignalReport, PolicyThemeSignal, ThemeSnapshot

POLICY_TAGS = {"policy", "official_policy", "state_council", "ministry", "regulator", "macro_policy"}


def is_policy_item(item: IntelItem) -> bool:
    tags = {tag.lower() for tag in item.tags}
    return bool(tags & POLICY_TAGS)


def _item_weight(item: IntelItem) -> float:
    tags = {tag.lower() for tag in item.tags}
    weight = 1.0
    if "state_council" in tags:
        weight += 1.5
    if "regulator" in tags:
        weight += 1.0
    if "ministry" in tags:
        weight += 0.8
    if "macro_policy" in tags:
        weight += 0.5
    return weight


def _policy_matched_themes(item: IntelItem, keywords_by_theme: Mapping[str, list[str]] | None = None) -> list[str]:
    if not keywords_by_theme:
        return item.matched_themes
    text = f"{item.title} {item.summary or ''}".lower()
    matches: list[str] = []
    for theme, keywords in keywords_by_theme.items():
        if any(keyword.lower() in text for keyword in keywords):
            matches.append(theme)
    return matches


def policy_counts_by_theme(items: list[IntelItem], keywords_by_theme: Mapping[str, list[str]] | None = None) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        if not is_policy_item(item):
            continue
        for theme in _policy_matched_themes(item, keywords_by_theme):
            counts[theme] += 1
    return dict(counts)


def policy_scores_by_theme(items: list[IntelItem], keywords_by_theme: Mapping[str, list[str]] | None = None) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    for item in items:
        if not is_policy_item(item):
            continue
        for theme in _policy_matched_themes(item, keywords_by_theme):
            scores[theme] += 18.0 * _item_weight(item)
    return {theme: round(min(100.0, score), 2) for theme, score in scores.items()}


def apply_policy_keyword_matches(items: list[IntelItem], keywords_by_theme: Mapping[str, list[str]]) -> list[IntelItem]:
    for item in items:
        if is_policy_item(item):
            item.matched_themes = _policy_matched_themes(item, keywords_by_theme)
    return items


def _theme_status_map(themes: list[ThemeSnapshot]) -> dict[str, str]:
    return {theme.name: theme.status for theme in themes}


def build_policy_signal_report(
    items: list[IntelItem],
    themes: list[ThemeSnapshot],
    keywords_by_theme: Mapping[str, list[str]] | None = None,
    limit: int = 8,
) -> PolicySignalReport:
    policy_items = [item for item in items if is_policy_item(item)]
    grouped: dict[str, list[IntelItem]] = defaultdict(list)
    matched_item_keys: set[tuple[str, str]] = set()
    for item in policy_items:
        matched_themes = _policy_matched_themes(item, keywords_by_theme)
        if not matched_themes:
            continue
        matched_item_keys.add((item.source, item.title))
        for theme in matched_themes:
            grouped[theme].append(item)

    scores = policy_scores_by_theme(policy_items, keywords_by_theme)
    status_by_theme = _theme_status_map(themes)
    theme_rank = {theme.name: index for index, theme in enumerate(themes)}
    signals: list[PolicyThemeSignal] = []
    for theme, evidence in grouped.items():
        sources = list(dict.fromkeys(item.source for item in evidence))
        signals.append(
            PolicyThemeSignal(
                theme=theme,
                theme_status=status_by_theme.get(theme, "未进入主线榜"),
                score=scores.get(theme, 0.0),
                item_count=len(evidence),
                sources=sources,
                evidence=evidence[:5],
            )
        )
    signals.sort(key=lambda item: (-item.score, theme_rank.get(item.theme, 999), item.theme))

    notes = [
        "政策催化只作为主线证据和加分项，不能替代价格趋势、成交热度和主题广度。",
        "优先统计带 policy/official 标签的官方来源；券商解读和新闻转载可作为补充，但不计入官方政策分。",
    ]
    if policy_items and not matched_item_keys:
        notes.append("本次抓到政策条目，但没有命中现有主题关键词；需要补充 policy_keywords 或人工归因。")
    if not policy_items:
        notes.append("本次没有抓到可用政策条目，需检查官方源可访问性。")

    return PolicySignalReport(
        signals=signals[:limit],
        total_policy_items=len(policy_items),
        matched_policy_items=len(matched_item_keys),
        notes=notes,
    )
