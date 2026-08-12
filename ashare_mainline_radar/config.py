from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_THEME_CONFIG = PROJECT_ROOT / "configs" / "theme_baskets.json"
DEFAULT_INTEL_CONFIG = PROJECT_ROOT / "configs" / "intel_sources.json"


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_project_path(path: str | Path, base: Path = PROJECT_ROOT) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return base / candidate


def sanitize_theme_config_instruments(
    theme_config: dict[str, Any],
    instruments: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Remove definitively mis-mapped theme vehicles using live instrument names.

    Theme members are curated manually, so an ETF ticker reuse or a typo can
    contaminate both breadth and momentum.  Validation is opt-in per theme via
    ``vehicle_name_keywords`` and deliberately keeps vehicles whose metadata is
    unavailable; only a confirmed name mismatch is excluded.
    """

    sanitized = deepcopy(theme_config)
    warnings: list[str] = []
    for theme in sanitized.get("themes", []):
        expected = [str(keyword).strip().lower() for keyword in theme.get("vehicle_name_keywords", []) if keyword]
        if not expected:
            continue
        valid_vehicles: list[str] = []
        for raw_symbol in theme.get("vehicles", []):
            symbol = str(raw_symbol)
            instrument = instruments.get(symbol)
            if not instrument:
                valid_vehicles.append(symbol)
                warnings.append(f"{theme['name']} 载体 {symbol} 缺少标的元数据，暂时保留并降级校验")
                continue
            name = str(instrument.get("name") or symbol)
            normalized_name = name.lower()
            if any(keyword in normalized_name for keyword in expected):
                valid_vehicles.append(symbol)
                continue
            warnings.append(
                f"{theme['name']} 载体 {symbol}（{name}）与预期关键词不符，已从本次主题评分和候选中剔除"
            )
        theme["vehicles"] = valid_vehicles
    return sanitized, warnings


def theme_symbol_map(theme_config: dict[str, Any]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for theme in theme_config.get("themes", []):
        name = str(theme["name"])
        symbols = (
            set(theme.get("symbols", []))
            | set(theme.get("vehicles", []))
            | set(theme.get("scoring_symbols", []))
            | set(theme.get("candidate_symbols", []))
        )
        for symbol in symbols:
            mapping.setdefault(symbol, []).append(name)
    return mapping


def theme_keywords(theme_config: dict[str, Any]) -> dict[str, list[str]]:
    keywords_by_theme: dict[str, list[str]] = {}
    for theme in theme_config.get("themes", []):
        raw_keywords = [*theme.get("keywords", []), *theme.get("policy_keywords", [])]
        keywords_by_theme[str(theme["name"])] = list(dict.fromkeys(str(keyword) for keyword in raw_keywords))
    return keywords_by_theme


def theme_policy_keywords(theme_config: dict[str, Any]) -> dict[str, list[str]]:
    keywords_by_theme: dict[str, list[str]] = {}
    for theme in theme_config.get("themes", []):
        raw_keywords = theme.get("policy_keywords") or theme.get("keywords", [])
        keywords_by_theme[str(theme["name"])] = list(dict.fromkeys(str(keyword) for keyword in raw_keywords))
    return keywords_by_theme


def configured_symbols(theme_config: dict[str, Any]) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()

    def add(symbol: str) -> None:
        if symbol and symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)

    for theme in theme_config.get("themes", []):
        for symbol in theme.get("symbols", []):
            add(str(symbol))
        for symbol in theme.get("vehicles", []):
            add(str(symbol))
        for symbol in theme.get("scoring_symbols", []):
            add(str(symbol))
        for symbol in theme.get("candidate_symbols", []):
            add(str(symbol))
    for item in theme_config.get("market_watchlist", []):
        add(str(item["symbol"]))
    for pair in (theme_config.get("cross_market") or {}).get("ah_pairs", []):
        add(str(pair.get("a_symbol") or ""))
    return symbols


def theme_scoring_symbols(theme: dict[str, Any]) -> list[str]:
    scoring_symbols = theme.get("scoring_symbols")
    if scoring_symbols:
        return list(dict.fromkeys(str(symbol) for symbol in scoring_symbols))
    return list(
        dict.fromkeys(
            [str(symbol) for symbol in theme.get("symbols", [])] + [str(symbol) for symbol in theme.get("vehicles", [])]
        )
    )


def theme_candidate_symbols(theme: dict[str, Any]) -> list[str]:
    configured = theme.get("candidate_symbols")
    symbols = configured if configured else theme.get("symbols", [])
    return list(
        dict.fromkeys([str(symbol) for symbol in symbols] + [str(symbol) for symbol in theme.get("vehicles", [])])
    )
