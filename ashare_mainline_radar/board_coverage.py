"""Board-level coverage observation: 当日热板 + 缺篮候选.

策划主线 stays in `theme_baskets.json` / `classify_theme`. This module only
observes Eastmoney boards under their native names/codes. Unmapped is not
“nearest theme”: 化肥 must not fold into 农业种植. Promotion into
THEME_PRESETS is manual.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable

from .eastmoney_concepts import THEME_PRESETS, fetch_board_list
from .models import BoardCoverageReport, BoardSnapshot

DEFAULT_SOURCE = "eastmoney"
HOT_BY_AMOUNT = 30
HOT_BY_CHANGE = 20
HOT_CAP = 40
PERSISTENCE_LOOKBACK_SESSIONS = 10
MISSING_BASKET_MIN_DAYS = 3
BOARD_CODE_IN_SOURCE = re.compile(r"([^,;()]+?)\((BK\d+)\)")
NAME_SUFFIXES = ("概念", "Ⅲ", "II", "行业")

COVERAGE_NOTES = (
    "这是覆盖观察，不是主线成立，也不是买入建议。",
    "东财板块保持原名和原代码；未覆盖不等于最近主题，不会把化肥并进农业种植。",
    f"缺篮候选：未映射且最近 {PERSISTENCE_LOOKBACK_SESSIONS} 个有快照的交易日里至少 {MISSING_BASKET_MIN_DAYS} 日出现在热板集合。",
    "入篮仍是人工：在 THEME_PRESETS 写明 boards 后执行 "
    "`python3 scripts/sync_theme_concepts.py --preset <主题> --write`，不要从热板自动改 theme_baskets.json。",
)


def _norm_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _norm_name(value: Any) -> str:
    return str(value or "").strip()


def _stem_name(name: str) -> str:
    text = name
    for suffix in NAME_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _add(bucket: dict[str, set[str]], key: str, theme: str) -> None:
    cleaned = _norm_name(key)
    if cleaned:
        bucket[cleaned].add(theme)


class BoardThemeMap:
    """Config-generated many-to-one map: several EM boards → one radar theme."""

    def __init__(self, by_code: dict[str, set[str]], by_exact_name: dict[str, set[str]], by_keyword: dict[str, set[str]]):
        self.by_code = by_code
        self.by_exact_name = by_exact_name
        self.by_keyword = by_keyword

    def map_board(self, board_code: str, board_name: str) -> tuple[str | None, str]:
        code = _norm_code(board_code)
        name = _norm_name(board_name)
        for bucket, key in (
            (self.by_code, code),
            (self.by_exact_name, name),
        ):
            themes = bucket.get(key) or set()
            if len(themes) == 1:
                return next(iter(themes)), "mapped"
            if len(themes) > 1:
                return None, "unmapped"
        keyword_hits: set[str] = set(self.by_keyword.get(name) or set())
        stem = _stem_name(name)
        if stem != name:
            keyword_hits.update(self.by_keyword.get(stem) or set())
        if len(keyword_hits) == 1:
            return next(iter(keyword_hits)), "mapped"
        return None, "unmapped"


def build_board_theme_map(
    theme_config: dict[str, Any] | None = None,
    presets: dict[str, dict[str, Any]] | None = None,
) -> BoardThemeMap:
    """Build the mapper from THEME_PRESETS + theme_baskets, not a chat-time list."""
    by_code: dict[str, set[str]] = defaultdict(set)
    by_exact_name: dict[str, set[str]] = defaultdict(set)
    by_keyword: dict[str, set[str]] = defaultdict(set)
    preset_book = presets if presets is not None else THEME_PRESETS

    for theme_name, preset in preset_book.items():
        _add(by_exact_name, theme_name, theme_name)
        _add(by_keyword, theme_name, theme_name)
        for board in preset.get("boards") or []:
            if not isinstance(board, dict):
                continue
            code = _norm_code(board.get("code"))
            label = _norm_name(board.get("name"))
            if code:
                by_code[code].add(theme_name)
            if label:
                by_exact_name[label].add(theme_name)
        for keyword in preset.get("keywords") or []:
            _add(by_keyword, str(keyword), theme_name)

    for theme in (theme_config or {}).get("themes") or []:
        if not isinstance(theme, dict) or not theme.get("name"):
            continue
        theme_name = str(theme["name"])
        _add(by_exact_name, theme_name, theme_name)
        _add(by_keyword, theme_name, theme_name)
        for board in theme.get("boards") or []:
            if not isinstance(board, dict):
                continue
            code = _norm_code(board.get("code"))
            label = _norm_name(board.get("name"))
            if code:
                by_code[code].add(theme_name)
            if label:
                by_exact_name[label].add(theme_name)
        source = str(theme.get("source") or "")
        for label, code in BOARD_CODE_IN_SOURCE.findall(source):
            by_code[_norm_code(code)].add(theme_name)
            _add(by_exact_name, label, theme_name)
        for keyword in theme.get("keywords") or []:
            _add(by_keyword, str(keyword), theme_name)

    return BoardThemeMap(dict(by_code), dict(by_exact_name), dict(by_keyword))


def _as_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _board_key(source: str, board_code: str) -> tuple[str, str]:
    return (source, _norm_code(board_code))


def select_hot_boards(
    boards: list[dict[str, Any]],
    *,
    source: str = DEFAULT_SOURCE,
    amount_limit: int = HOT_BY_AMOUNT,
    change_limit: int = HOT_BY_CHANGE,
    cap: int = HOT_CAP,
) -> list[dict[str, Any]]:
    """Keep a lean free-tier hot set: Top N by amount ∪ Top N by change."""
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in boards:
        if not isinstance(raw, dict):
            continue
        code = _norm_code(raw.get("code") or raw.get("board_code"))
        name = _norm_name(raw.get("name") or raw.get("board_name"))
        if not code or not name:
            continue
        kind = str(raw.get("kind") or raw.get("board_kind") or "concept")
        if kind not in {"concept", "industry"}:
            kind = "concept"
        row = {
            "source": str(raw.get("source") or source),
            "board_kind": kind,
            "board_code": code,
            "board_name": name,
            "change_pct": _as_float(raw.get("change_pct")),
            "amount": _as_float(raw.get("amount")),
        }
        unique[_board_key(row["source"], code)] = row

    rows = list(unique.values())
    by_amount = sorted(
        rows,
        key=lambda item: (item["amount"] is not None, item["amount"] or 0.0, item["change_pct"] or 0.0),
        reverse=True,
    )[:amount_limit]
    by_change = sorted(
        rows,
        key=lambda item: (item["change_pct"] is not None, item["change_pct"] or 0.0, item["amount"] or 0.0),
        reverse=True,
    )[:change_limit]
    chosen: dict[tuple[str, str], dict[str, Any]] = {}
    for item in [*by_amount, *by_change]:
        chosen[_board_key(item["source"], item["board_code"])] = item
        if len(chosen) >= cap:
            break
    return sorted(
        chosen.values(),
        key=lambda item: (item["amount"] or 0.0, item["change_pct"] or 0.0, item["board_code"]),
        reverse=True,
    )


def fetch_hot_boards(
    *,
    fetch_list: Callable[..., list[dict[str, Any]]] = fetch_board_list,
    source: str = DEFAULT_SOURCE,
) -> list[dict[str, Any]]:
    """Pull a lean Eastmoney concept+industry universe for Daily, not the full ~400 dump."""
    collected: list[dict[str, Any]] = []
    for kind in ("concept", "industry"):
        for sort_fid, pages, page_size in (("f6", 1, 50), ("f3", 1, 30)):
            rows = fetch_list(kind, pages=pages, page_size=page_size, sort_fid=sort_fid)
            for row in rows:
                item = dict(row)
                item["source"] = source
                item["kind"] = kind
                collected.append(item)
    return collected


def count_persistence_days(
    source: str,
    board_code: str,
    market_date: str,
    history: list[dict[str, Any]],
    *,
    lookback_sessions: int = PERSISTENCE_LOOKBACK_SESSIONS,
) -> int:
    """Count how many recent snapshot sessions this board appeared in the hot set."""
    code = _norm_code(board_code)
    present_dates = {
        str(row.get("market_date"))
        for row in history
        if str(row.get("source") or source) == source
        and _norm_code(row.get("board_code") or row.get("code")) == code
        and str(row.get("market_date") or "") <= market_date
    }
    present_dates.add(market_date)
    all_sessions = sorted(
        {
            str(row.get("market_date"))
            for row in history
            if str(row.get("market_date") or "") <= market_date
        }
        | {market_date}
    )
    recent = all_sessions[-lookback_sessions:]
    return sum(1 for session in recent if session in present_dates)


def annotate_hot_boards(
    hot_boards: list[dict[str, Any]],
    mapper: BoardThemeMap,
    *,
    market_date: str,
    history: list[dict[str, Any]] | None = None,
    lookback_sessions: int = PERSISTENCE_LOOKBACK_SESSIONS,
) -> list[BoardSnapshot]:
    snapshots: list[BoardSnapshot] = []
    for row in hot_boards:
        mapped_theme, coverage = mapper.map_board(row["board_code"], row["board_name"])
        snapshots.append(
            BoardSnapshot(
                market_date=market_date,
                source=str(row.get("source") or DEFAULT_SOURCE),
                board_kind=str(row.get("board_kind") or "concept"),
                board_code=row["board_code"],
                board_name=row["board_name"],
                change_pct=row.get("change_pct"),
                amount=row.get("amount"),
                mapped_theme=mapped_theme,
                coverage=coverage,
                persistence_days=count_persistence_days(
                    str(row.get("source") or DEFAULT_SOURCE),
                    row["board_code"],
                    market_date,
                    history or [],
                    lookback_sessions=lookback_sessions,
                ),
            )
        )
    snapshots.sort(
        key=lambda item: (
            item.persistence_days,
            item.amount or 0.0,
            item.change_pct or 0.0,
            item.board_code,
        ),
        reverse=True,
    )
    return snapshots


def missing_basket_candidates(
    snapshots: list[BoardSnapshot],
    *,
    min_days: int = MISSING_BASKET_MIN_DAYS,
) -> list[BoardSnapshot]:
    return [
        item
        for item in snapshots
        if item.coverage == "unmapped" and item.persistence_days >= min_days
    ]


def mapped_hot_footnote(snapshots: list[BoardSnapshot], *, limit: int = 6) -> list[BoardSnapshot]:
    mapped = [item for item in snapshots if item.coverage == "mapped"]
    mapped.sort(key=lambda item: (item.amount or 0.0, item.change_pct or 0.0), reverse=True)
    return mapped[:limit]


def build_board_coverage_report(
    theme_config: dict[str, Any] | None,
    boards: list[dict[str, Any]],
    *,
    market_date: str,
    history: list[dict[str, Any]] | None = None,
    source: str = DEFAULT_SOURCE,
    min_days: int = MISSING_BASKET_MIN_DAYS,
    mapper: BoardThemeMap | None = None,
) -> BoardCoverageReport:
    resolved_mapper = mapper or build_board_theme_map(theme_config)
    hot = select_hot_boards(boards, source=source)
    snapshots = annotate_hot_boards(hot, resolved_mapper, market_date=market_date, history=history)
    return BoardCoverageReport(
        source=source,
        scanned=len({_norm_code(item.get("code") or item.get("board_code")) for item in boards if isinstance(item, dict)}),
        snapshots=snapshots,
        missing_basket=missing_basket_candidates(snapshots, min_days=min_days),
        mapped_footnote=mapped_hot_footnote(snapshots),
        notes=list(COVERAGE_NOTES),
    )


def snapshot_rows(report: BoardCoverageReport, *, run_key: str | None, updated_at: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in report.snapshots:
        rows.append(
            {
                "market_date": item.market_date,
                "source": item.source,
                "board_kind": item.board_kind,
                "board_code": item.board_code,
                "board_name": item.board_name,
                "change_pct": item.change_pct,
                "amount": item.amount,
                "mapped_theme": item.mapped_theme,
                "coverage": item.coverage,
                "persistence_days": item.persistence_days,
                "run_key": run_key,
                "updated_at": updated_at,
            }
        )
    return rows


def coverage_summary(report: BoardCoverageReport) -> dict[str, Any]:
    return {
        "source": report.source,
        "scanned": report.scanned,
        "hot_count": len(report.snapshots),
        "missing_basket_count": len(report.missing_basket),
        "missing_basket": [item.to_dict() for item in report.missing_basket[:12]],
        "mapped_footnote": [item.to_dict() for item in report.mapped_footnote[:6]],
        "notes": list(report.notes),
    }
