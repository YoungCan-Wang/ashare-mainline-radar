from __future__ import annotations

import json
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


def theme_symbol_map(theme_config: dict[str, Any]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for theme in theme_config.get("themes", []):
        name = str(theme["name"])
        symbols = set(theme.get("symbols", [])) | set(theme.get("vehicles", []))
        for symbol in symbols:
            mapping.setdefault(symbol, []).append(name)
    return mapping


def theme_keywords(theme_config: dict[str, Any]) -> dict[str, list[str]]:
    return {
        str(theme["name"]): [str(keyword) for keyword in theme.get("keywords", [])]
        for theme in theme_config.get("themes", [])
    }


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
    for item in theme_config.get("market_watchlist", []):
        add(str(item["symbol"]))
    return symbols
