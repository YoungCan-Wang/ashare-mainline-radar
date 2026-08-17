#!/usr/bin/env python3
"""Refresh curated theme baskets from East Money concept/industry boards.

Examples:
  python3 scripts/sync_theme_concepts.py --list-concepts --keyword 消费
  python3 scripts/sync_theme_concepts.py --preset 大消费 --dry-run
  python3 scripts/sync_theme_concepts.py --all-presets --offline --write
  python3 scripts/sync_theme_concepts.py --preset 光伏与储能 --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ashare_mainline_radar.config import DEFAULT_THEME_CONFIG, load_json
from ashare_mainline_radar.eastmoney_concepts import (
    THEME_PRESETS,
    build_theme_from_preset,
    fetch_board_list,
    filter_boards,
    offline_theme_from_preset,
    upsert_theme,
)


def _print_theme(theme: dict) -> None:
    print(json.dumps(theme, ensure_ascii=False, indent=2))


def _build(preset: str, *, offline: bool, as_of: str | None) -> dict:
    if offline:
        return offline_theme_from_preset(preset, as_of=as_of)
    try:
        return build_theme_from_preset(preset, as_of=as_of)
    except (RuntimeError, OSError, TimeoutError, ValueError) as exc:
        print(
            f"warning: live preset {preset} failed; falling back to seed symbols: {exc}",
            file=sys.stderr,
        )
        return offline_theme_from_preset(preset, as_of=as_of)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync theme baskets from East Money boards")
    parser.add_argument("--preset", choices=sorted(THEME_PRESETS), help="Build/update one curated preset")
    parser.add_argument("--all-presets", action="store_true", help="Build/update every curated preset")
    parser.add_argument("--list-concepts", action="store_true", help="List East Money concept boards")
    parser.add_argument("--list-industries", action="store_true", help="List East Money industry boards")
    parser.add_argument("--list-presets", action="store_true", help="List curated tradable mainline presets")
    parser.add_argument("--keyword", action="append", default=[], help="Filter board names; repeatable")
    parser.add_argument("--config", type=Path, default=DEFAULT_THEME_CONFIG, help="Path to theme_baskets.json")
    parser.add_argument("--write", action="store_true", help="Write into theme_baskets.json")
    parser.add_argument("--dry-run", action="store_true", help="Print proposed theme(s) without writing")
    parser.add_argument("--offline", action="store_true", help="Use seed symbols only; skip East Money HTTP")
    parser.add_argument("--as-of", default=None, help="Optional source stamp YYYY-MM-DD")
    args = parser.parse_args(argv)

    if args.list_presets:
        for name in sorted(THEME_PRESETS):
            preset = THEME_PRESETS[name]
            boards = ", ".join(board["name"] for board in preset["boards"])
            print(f"{name} | seeds={len(preset['seed_symbols'])} | boards={boards}")
        print(f"total={len(THEME_PRESETS)}")
        return 0

    if args.list_concepts or args.list_industries:
        boards = []
        if args.list_concepts:
            boards.extend(fetch_board_list("concept"))
        if args.list_industries:
            boards.extend(fetch_board_list("industry"))
        boards = filter_boards(boards, args.keyword)
        for board in boards:
            change = board.get("change_pct")
            change_text = f"{change:>7}" if isinstance(change, (int, float)) else f"{change!s:>7}"
            print(f"{change_text} | {board['kind']:<8} | {board['code']} | {board['name']}")
        print(f"total={len(boards)}")
        return 0

    presets = sorted(THEME_PRESETS) if args.all_presets else ([args.preset] if args.preset else [])
    if not presets:
        parser.error("provide --preset/--all-presets, or use --list-presets/--list-concepts/--list-industries")

    themes = [_build(name, offline=args.offline, as_of=args.as_of) for name in presets]
    if args.dry_run or not args.write:
        for theme in themes:
            _print_theme(theme)
            print()
        if not args.write:
            print("# dry-run only; pass --write to update theme_baskets.json", file=sys.stderr)
        return 0

    config_path = args.config.expanduser()
    theme_config = load_json(config_path)
    for theme in themes:
        theme_config = upsert_theme(theme_config, theme)
    config_path.write_text(json.dumps(theme_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    names = ", ".join(theme["name"] for theme in themes)
    print(f"updated {config_path} themes={names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
