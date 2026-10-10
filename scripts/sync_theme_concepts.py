#!/usr/bin/env python3
"""Refresh curated theme baskets from East Money concept/industry boards.

Examples:
  python3 scripts/sync_theme_concepts.py --list-concepts --keyword 消费
  python3 scripts/sync_theme_concepts.py --preset 大消费 --dry-run
  python3 scripts/sync_theme_concepts.py --all-presets --offline --write
  python3 scripts/sync_theme_concepts.py --preset 光伏与储能 --write

The weekly GitHub Action passes ``--enforce-quality-gates``. A failed gate
prints ``QUALITY gate=skip`` and leaves the config file untouched (exit 0).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ashare_mainline_radar.config import DEFAULT_THEME_CONFIG, load_json  # noqa: E402
from ashare_mainline_radar.eastmoney_concepts import (  # noqa: E402
    THEME_PRESETS,
    build_theme_from_preset,
    fetch_board_list,
    filter_boards,
    offline_theme_from_preset,
    upsert_theme,
)

# Fail closed before a weekly commit. One flaky board is normal; a run that is
# mostly HTTP 502 seed-fallback, or that rewrites the scoring universe, must
# not land on main. Thresholds are strict greater-than.
MAX_BOARD_FETCH_FAILURE_RATIO = 0.25
MAX_SEED_FALLBACK_PRESET_RATIO = 0.20
MAX_SYMBOL_COUNT_RELATIVE_DELTA = 0.15
MAX_THEME_SYMBOL_COUNT_DELTA = 4
MAX_CHURN_RATIO = 0.25
MAX_NON_SEED_CHURN_RATIO = 0.15


def _print_theme(theme: dict) -> None:
    print(json.dumps(theme, ensure_ascii=False, indent=2))


def _new_quality() -> dict[str, int]:
    return {
        "boards_attempted": 0,
        "boards_failed": 0,
        "presets": 0,
        "seed_fallback_presets": 0,
    }


def _build(preset: str, *, offline: bool, as_of: str | None, quality: dict[str, int]) -> dict:
    board_count = len(THEME_PRESETS[preset].get("boards") or [])
    if offline:
        quality["presets"] += 1
        quality["boards_attempted"] += board_count
        quality["boards_failed"] += board_count
        quality["seed_fallback_presets"] += 1
        return offline_theme_from_preset(preset, as_of=as_of)
    slot: dict[str, int] = {}
    try:
        theme = build_theme_from_preset(preset, as_of=as_of, fetch_stats=slot)
    except (RuntimeError, OSError, TimeoutError, ValueError) as exc:
        print(
            f"warning: live preset {preset} failed; falling back to seed symbols: {exc}",
            file=sys.stderr,
        )
        quality["presets"] += 1
        quality["boards_attempted"] += board_count
        quality["boards_failed"] += board_count
        quality["seed_fallback_presets"] += 1
        return offline_theme_from_preset(preset, as_of=as_of)
    quality["presets"] += 1
    quality["boards_attempted"] += int(slot.get("attempted", 0))
    quality["boards_failed"] += int(slot.get("failed", 0))
    if int(slot.get("live_rows", 0)) == 0:
        quality["seed_fallback_presets"] += 1
    return theme


def _theme_symbols(theme: dict[str, Any] | None) -> list[str]:
    if not theme:
        return []
    return [str(symbol) for symbol in theme.get("symbols") or []]


def evaluate_sync_quality(
    *,
    previous_themes: list[dict[str, Any]],
    proposed_themes: list[dict[str, Any]],
    boards_attempted: int,
    boards_failed: int,
    presets: int,
    seed_fallback_presets: int,
    seed_symbols_by_theme: dict[str, list[str]],
) -> dict[str, Any]:
    """Return a fail-closed report. ``ok`` is false when any gate trips."""
    reasons: list[str] = []
    board_failure_ratio = (boards_failed / boards_attempted) if boards_attempted else 1.0
    seed_fallback_ratio = (seed_fallback_presets / presets) if presets else 1.0
    if boards_attempted == 0:
        reasons.append("East Money board fetch failure ratio is unknown (no boards attempted)")
    elif board_failure_ratio > MAX_BOARD_FETCH_FAILURE_RATIO:
        reasons.append(
            "East Money board fetch failure ratio "
            f"{board_failure_ratio:.3f} exceeds {MAX_BOARD_FETCH_FAILURE_RATIO:.3f} "
            f"({boards_failed}/{boards_attempted})"
        )
    if presets == 0:
        reasons.append("seed-fallback preset ratio is unknown (no presets synced)")
    elif seed_fallback_ratio > MAX_SEED_FALLBACK_PRESET_RATIO:
        reasons.append(
            "seed-fallback preset ratio "
            f"{seed_fallback_ratio:.3f} exceeds {MAX_SEED_FALLBACK_PRESET_RATIO:.3f} "
            f"({seed_fallback_presets}/{presets})"
        )

    previous_by = {str(theme.get("name")): theme for theme in previous_themes}
    previous_count = 0
    proposed_count = 0
    previous_pairs: set[tuple[str, str]] = set()
    proposed_pairs: set[tuple[str, str]] = set()
    dropped_seed_leaders = 0
    for theme in proposed_themes:
        name = str(theme.get("name"))
        new_symbols = _theme_symbols(theme)
        old_symbols = _theme_symbols(previous_by.get(name))
        previous_count += len(old_symbols)
        proposed_count += len(new_symbols)
        if abs(len(new_symbols) - len(old_symbols)) > MAX_THEME_SYMBOL_COUNT_DELTA:
            reasons.append(
                f"abnormal symbol count for {name}: {len(old_symbols)} -> {len(new_symbols)} "
                f"(max delta {MAX_THEME_SYMBOL_COUNT_DELTA})"
            )
        previous_pairs.update((name, symbol) for symbol in old_symbols)
        proposed_pairs.update((name, symbol) for symbol in new_symbols)
        seeds = {str(symbol) for symbol in seed_symbols_by_theme.get(name, [])}
        dropped_seed_leaders += len((set(old_symbols) & seeds) - set(new_symbols))

    symbol_count_relative_delta = abs(proposed_count - previous_count) / max(previous_count, 1)
    if symbol_count_relative_delta > MAX_SYMBOL_COUNT_RELATIVE_DELTA:
        reasons.append(
            "abnormal symbol count vs previous file: "
            f"{previous_count} -> {proposed_count} "
            f"(relative delta {symbol_count_relative_delta:.3f} exceeds {MAX_SYMBOL_COUNT_RELATIVE_DELTA:.3f})"
        )

    changed_pairs = previous_pairs.symmetric_difference(proposed_pairs)
    churn_ratio = len(changed_pairs) / max(len(previous_pairs), 1)
    non_seed_changed = 0
    for name, symbol in changed_pairs:
        seeds = {str(item) for item in seed_symbols_by_theme.get(name, [])}
        if symbol not in seeds:
            non_seed_changed += 1
    non_seed_churn_ratio = non_seed_changed / max(len(previous_pairs), 1)
    if churn_ratio > MAX_CHURN_RATIO:
        reasons.append(
            f"abnormal churn ratio {churn_ratio:.3f} exceeds {MAX_CHURN_RATIO:.3f} "
            f"({len(changed_pairs)} symbol slots changed)"
        )
    if non_seed_churn_ratio > MAX_NON_SEED_CHURN_RATIO:
        reasons.append(
            "abnormal small-cap churn ratio "
            f"{non_seed_churn_ratio:.3f} exceeds {MAX_NON_SEED_CHURN_RATIO:.3f} "
            f"({non_seed_changed} non-seed symbol slots changed)"
        )
    if dropped_seed_leaders:
        reasons.append(f"abnormal churn: {dropped_seed_leaders} seed leaders dropped")

    return {
        "ok": not reasons,
        "reasons": reasons,
        "board_failure_ratio": board_failure_ratio,
        "seed_fallback_ratio": seed_fallback_ratio,
        "symbol_count_relative_delta": symbol_count_relative_delta,
        "churn_ratio": churn_ratio,
        "non_seed_churn_ratio": non_seed_churn_ratio,
        "dropped_seed_leaders": dropped_seed_leaders,
        "previous_symbol_count": previous_count,
        "proposed_symbol_count": proposed_count,
    }


def _print_quality(report: dict[str, Any]) -> None:
    gate = "pass" if report["ok"] else "skip"
    print(
        f"QUALITY gate={gate} "
        f"board_failure_ratio={report['board_failure_ratio']:.3f} "
        f"seed_fallback_ratio={report['seed_fallback_ratio']:.3f} "
        f"symbol_count={report['previous_symbol_count']}->{report['proposed_symbol_count']} "
        f"symbol_count_relative_delta={report['symbol_count_relative_delta']:.3f} "
        f"churn_ratio={report['churn_ratio']:.3f} "
        f"non_seed_churn_ratio={report['non_seed_churn_ratio']:.3f} "
        f"dropped_seed_leaders={report['dropped_seed_leaders']}"
    )
    for reason in report["reasons"]:
        print(f"QUALITY reason={reason}")


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
    parser.add_argument(
        "--enforce-quality-gates",
        action="store_true",
        help="Skip the write when board failures, seed fallback, symbol count, or churn exceed limits",
    )
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

    quality = _new_quality()
    themes = [_build(name, offline=args.offline, as_of=args.as_of, quality=quality) for name in presets]
    if args.dry_run or not args.write:
        for theme in themes:
            _print_theme(theme)
            print()
        if not args.write:
            print("# dry-run only; pass --write to update theme_baskets.json", file=sys.stderr)
        return 0

    config_path = args.config.expanduser()
    theme_config = load_json(config_path)
    if args.enforce_quality_gates:
        seed_symbols_by_theme = {
            name: list(THEME_PRESETS[name].get("seed_symbols") or []) for name in presets
        }
        report = evaluate_sync_quality(
            previous_themes=list(theme_config.get("themes") or []),
            proposed_themes=themes,
            boards_attempted=quality["boards_attempted"],
            boards_failed=quality["boards_failed"],
            presets=quality["presets"],
            seed_fallback_presets=quality["seed_fallback_presets"],
            seed_symbols_by_theme=seed_symbols_by_theme,
        )
        _print_quality(report)
        if not report["ok"]:
            print("quality gates failed; theme_baskets.json not written")
            return 0

    for theme in themes:
        theme_config = upsert_theme(theme_config, theme)
    config_path.write_text(json.dumps(theme_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    names = ", ".join(theme["name"] for theme in themes)
    print(f"updated {config_path} themes={names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
