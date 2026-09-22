"""Wire the Fibonacci profit-space ranking into the daily mainline funnel.

The evening job still writes `fib_profit_space_daily`. The daily path ranks the
bars it already fetched, shows that slice on the production card, and persists
it like the other selection pools. When a successful published board exists for
the same as-of, that board replaces the in-process ranking.

Shadow eligibility is a smaller, separate list. It never creates a
`mainline-v1` plan and never sends a live order.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import date
from typing import Any, Callable
from urllib.request import urlopen

from .execution import build_trade_execution_plan, is_fund_security
from .fib_profit_space import (
    SUCCESS_STATUS,
    UNRUN_STATUS,
    measure_rows,
    name_is_st,
    published_board,
)
from .models import FibProfitSpaceCandidate, FibProfitSpacePool, KlineSeries, NextBuyReport, RadarReport, safe_change
from .supabase_rest import fetch_rows

FIB_POOL_ROLE = "fib_profit_space"
FIB_CARD_LIMIT = 12
FIB_SHADOW_SCAN = 40
FIB_SHADOW_CAP = 5
FIB_SHADOW_MIN_REMAINING_SPACE_PCT = 0.08
FIB_SHADOW_MAX_POSITION = 0.12
FIB_SHADOW_HOLD_DAYS = 15
FIB_THEME = "斐波那契赚钱空间"


def purchase_pool_symbols(next_buy: NextBuyReport) -> set[str]:
    """Symbols that become production paper plans: primary plus alternatives."""
    symbols: set[str] = set()
    if next_buy.primary is not None and next_buy.primary.symbol:
        symbols.add(next_buy.primary.symbol)
    for plan in next_buy.alternatives:
        if plan.symbol:
            symbols.add(plan.symbol)
    return symbols


def _bar_change(series: KlineSeries) -> float | None:
    if len(series.close) < 2:
        return None
    return safe_change(series.close[-1], series.close[-2])


def _candidate_from_row(row: Any, change: float | None) -> FibProfitSpaceCandidate | None:
    symbol = str(getattr(row, "code", None) or (row.get("code") if isinstance(row, dict) else "") or "")
    if not symbol:
        return None
    remaining = getattr(row, "remaining_space_pct", None) if not isinstance(row, dict) else row.get("remaining_space_pct")
    close = getattr(row, "close", None) if not isinstance(row, dict) else row.get("close")
    rank = getattr(row, "rank", None) if not isinstance(row, dict) else row.get("rank")
    if remaining is None or close is None or rank is None:
        return None
    name = str(getattr(row, "name", None) if not isinstance(row, dict) else row.get("name") or symbol)
    is_st = bool(getattr(row, "is_st", False) if not isinstance(row, dict) else row.get("is_st"))
    if not is_st:
        is_st = name_is_st(name)
    full_box = getattr(row, "full_box_pct", None) if not isinstance(row, dict) else row.get("full_box_pct")
    lower_source = getattr(row, "lower_source", None) if not isinstance(row, dict) else row.get("lower_source")
    valid = bool(getattr(row, "valid_flag", False) if not isinstance(row, dict) else row.get("valid_flag"))
    remaining_value = float(remaining)
    score = round(remaining_value * 100, 2)
    return FibProfitSpaceCandidate(
        symbol=symbol,
        name=name,
        rank=int(rank),
        last_close=float(close),
        remaining_space_pct=remaining_value,
        full_box_pct=float(full_box) if full_box is not None else None,
        valid_flag=valid,
        is_st=is_st,
        lower_source=str(lower_source) if lower_source else None,
        daily_change_pct=change,
        score=score,
        priority_score=score,
    )


def _base_notes(*, partial: bool) -> list[str]:
    notes = [
        "几何与 fib_profit_space_daily 相同：有效几何按剩余空间从大到小，ST 留在榜内。",
        (
            "影子买入池只收非 ST、非基金、剩余空间不低于 "
            f"{FIB_SHADOW_MIN_REMAINING_SPACE_PCT * 100:.0f}%、且不在当日 next_buy 主池里的名字。"
        ),
        "这些计划只写 fib-profit-space-shadow-v1，不写生产策略 mainline-v1，也不下实盘单。",
    ]
    if partial:
        notes.append("本次不是全市场扫描，榜单只覆盖日报已经抓到的标的。")
    return notes


def select_fib_shadow_members(
    candidates: list[FibProfitSpaceCandidate],
    *,
    gate_level: str,
    occupied_symbols: set[str],
) -> list[FibProfitSpaceCandidate]:
    """Conservative shadow-only names. Red gate (暂停新仓) adds nobody."""
    if gate_level == "red":
        return []
    eligible: list[FibProfitSpaceCandidate] = []
    seen: set[str] = set()
    ordered = sorted(candidates, key=lambda item: (item.rank, item.symbol))
    for item in ordered[:FIB_SHADOW_SCAN]:
        if item.symbol in seen or item.symbol in occupied_symbols:
            continue
        if not item.valid_flag or item.is_st or name_is_st(item.name) or is_fund_security(item.name):
            continue
        if item.remaining_space_pct < FIB_SHADOW_MIN_REMAINING_SPACE_PCT or item.last_close <= 0:
            continue
        seen.add(item.symbol)
        execution = build_trade_execution_plan(
            item.last_close,
            "趋势延续",
            hold_days=FIB_SHADOW_HOLD_DAYS,
            max_position_fraction=FIB_SHADOW_MAX_POSITION,
        )
        eligible.append(
            replace(
                item,
                theme=FIB_THEME,
                decision="赚钱空间观察，等待回踩",
                execution_status="watching",
                entry_mode=execution.entry_mode,
                entry_zone_low=execution.entry_zone_low,
                entry_zone_high=execution.entry_zone_high,
                confirm_price=execution.confirm_price,
                stop_price=execution.stop_price,
                valid_for_days=execution.valid_for_days,
                max_hold_days=execution.max_hold_days,
                max_position_fraction=execution.max_position_fraction,
                initial_position_fraction=execution.initial_position_fraction,
            )
        )
        if len(eligible) >= FIB_SHADOW_CAP:
            break
    return eligible


def _pool_from_candidates(
    ranked: list[FibProfitSpaceCandidate],
    *,
    state: str,
    as_of: str | None,
    source: str,
    scanned: int,
    gate_level: str,
    occupied_symbols: set[str],
    partial: bool,
) -> FibProfitSpacePool:
    card = ranked[:FIB_CARD_LIMIT]
    shadow = select_fib_shadow_members(ranked, gate_level=gate_level, occupied_symbols=occupied_symbols)
    notes = _base_notes(partial=partial)
    if gate_level == "red":
        notes.append("交易闸门为暂停新仓，赚钱空间不进入影子买入池。")
    return FibProfitSpacePool(
        state=state,
        as_of=as_of,
        source=source,
        scanned=scanned,
        candidates=card,
        shadow_candidates=shadow,
        notes=notes,
    )


def build_online_fib_pool(
    *,
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    as_of: date | None,
    gate_level: str,
    occupied_symbols: set[str],
    partial: bool = False,
) -> FibProfitSpacePool:
    items: list[tuple[str, str, KlineSeries]] = []
    for symbol, series in klines.items():
        instrument = instruments.get(symbol) or {}
        name = str(instrument.get("name") or symbol)
        items.append((symbol, name, series))
    if not items:
        return FibProfitSpacePool(
            state=UNRUN_STATUS,
            as_of=as_of.isoformat() if as_of else None,
            source="unrun",
            scanned=0,
            notes=["日报没有可用日 K，赚钱空间记为未运行。"],
        )
    measured = measure_rows(items, asof=as_of)
    changes = {symbol: _bar_change(series) for symbol, series in klines.items()}
    ranked: list[FibProfitSpaceCandidate] = []
    for row in measured:
        if not row.valid_flag or row.rank is None:
            continue
        candidate = _candidate_from_row(row, changes.get(row.code))
        if candidate is not None:
            ranked.append(candidate)
    ranked.sort(key=lambda item: item.rank)
    return _pool_from_candidates(
        ranked,
        state=SUCCESS_STATUS,
        as_of=as_of.isoformat() if as_of else None,
        source="daily_klines",
        scanned=len(items),
        gate_level=gate_level,
        occupied_symbols=occupied_symbols,
        partial=partial,
    )


def _published_changes(report: RadarReport) -> dict[str, float]:
    changes: dict[str, float] = {}
    for item in (*report.fib_profit_space.candidates, *report.fib_profit_space.shadow_candidates):
        if item.daily_change_pct is not None:
            changes[item.symbol] = item.daily_change_pct
    for item in report.strong_stocks.candidates:
        if item.daily_change_pct is not None:
            changes.setdefault(item.symbol, item.daily_change_pct)
    return changes


def apply_published_fib_board(
    report: RadarReport,
    *,
    supabase_url: str | None = None,
    supabase_publishable_key: str | None = None,
    radar_ingest_key: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> RadarReport:
    """Prefer the published success board for this as-of when it is already stored."""
    as_of = report.data_as_of
    url = supabase_url or os.getenv("SUPABASE_URL")
    api_key = supabase_publishable_key or os.getenv("SUPABASE_PUBLISHABLE_KEY")
    ingest_key = radar_ingest_key or os.getenv("RADAR_INGEST_KEY")
    if not as_of or not url or not api_key or not ingest_key:
        return report
    try:
        status_rows = fetch_rows(
            url,
            api_key,
            ingest_key,
            "fib_profit_space_run_status",
            order="asof_date.desc",
            max_rows=1,
            filters={"asof_date": f"eq.{as_of}"},
            opener=opener,
        )
        status = str(status_rows[0].get("status") or "") if status_rows else ""
        daily_rows = fetch_rows(
            url,
            api_key,
            ingest_key,
            "fib_profit_space_daily",
            order="rank.asc.nullslast",
            max_rows=FIB_SHADOW_SCAN,
            filters={"asof_date": f"eq.{as_of}"},
            opener=opener,
        )
    except (OSError, RuntimeError, ValueError):
        return report
    board = published_board(status, daily_rows)
    if board["state"] != SUCCESS_STATUS:
        return report
    changes = _published_changes(report)
    ranked: list[FibProfitSpaceCandidate] = []
    for row in board["rows"]:
        candidate = _candidate_from_row(row, changes.get(str(row.get("code") or "")))
        if candidate is not None:
            ranked.append(candidate)
    ranked.sort(key=lambda item: item.rank)
    pool = _pool_from_candidates(
        ranked,
        state=SUCCESS_STATUS,
        as_of=as_of,
        source="published_board",
        scanned=int(status_rows[0].get("symbol_count") or len(daily_rows)) if status_rows else len(daily_rows),
        gate_level=report.trading_gate.level,
        occupied_symbols=purchase_pool_symbols(report.next_buy),
        partial=report.mode != "universe",
    )
    pool.notes.insert(0, "排名来自当日已发布的赚钱空间成功榜。")
    report.fib_profit_space = pool
    return report
