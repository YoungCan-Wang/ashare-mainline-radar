#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ashare_mainline_radar.fib_profit_space import (
    GEOMETRY_VERSION,
    SUCCESS_STATUS,
    UNRUN_STATUS,
    FibProfitSpaceError,
    build_fib_profit_space,
    failure_asof,
    persist_fib_profit_space,
    supabase_credentials,
)
from ashare_mainline_radar.tickflow import TickFlowClient


def _parse_asof(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise FibProfitSpaceError("as-of must use YYYY-MM-DD") from exc


def _summary(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _top_rows(rows: list, limit: int = 20) -> list[dict[str, object]]:
    ranked = [row for row in rows if row.rank is not None]
    ranked.sort(key=lambda row: int(row.rank))
    return [
        {
            "rank": row.rank,
            "code": row.code,
            "name": row.name,
            "remaining_space_pct": row.as_db()["remaining_space_pct"],
            "is_st": row.is_st,
            "valid_flag": row.valid_flag,
        }
        for row in ranked[:limit]
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rank A-share Fibonacci profit space and store it.")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--as-of", default=os.getenv("FIB_AS_OF") or None)
    parser.add_argument("--universe", default=os.getenv("FIB_UNIVERSE") or "CN_Equity_A")
    parser.add_argument("--profile", default=os.getenv("FIB_PROFIT_SPACE_PROFILE") or "production")
    parser.add_argument("--summary", default="reports/fib/summary.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    requested = args.max_symbols
    if requested is None:
        raw_limit = os.getenv("FIB_MAX_SYMBOLS") or "0"
        requested = int(raw_limit)
    summary_path = Path(args.summary)
    state: dict[str, object] = {"asof": None, "credentials": None}

    def mark_unrun(message: str) -> None:
        credentials = state["credentials"]
        if not isinstance(credentials, tuple):
            return
        url, api_key, ingest_key = credentials
        asof = state["asof"] if isinstance(state["asof"], date) else failure_asof()
        try:
            persist_fib_profit_space(
                supabase_url=url,
                supabase_publishable_key=api_key,
                radar_ingest_key=ingest_key,
                run=None,
                status=UNRUN_STATUS,
                message=message,
                asof=asof,
            )
        except Exception as exc:
            print(f"could not record {UNRUN_STATUS}: {type(exc).__name__}: {exc}", file=sys.stderr)

    def _on_term(_signum: int, _frame: object) -> None:
        mark_unrun("terminated before a complete ranking")
        raise SystemExit(1)

    signal.signal(signal.SIGTERM, _on_term)
    try:
        if not args.dry_run:
            state["credentials"] = supabase_credentials()
        run = build_fib_profit_space(
            client=TickFlowClient(),
            max_symbols=requested,
            profile=str(args.profile),
            universe_id=str(args.universe),
            as_of=_parse_asof(args.as_of),
        )
        state["asof"] = run.asof_date
        message = (
            f"{GEOMETRY_VERSION} symbols={len(run.rows)} valid={run.valid_count} ranked={run.ranked_count}"
        )
        if not args.dry_run:
            credentials = state["credentials"]
            if not isinstance(credentials, tuple):
                raise FibProfitSpaceError("supabase credentials missing")
            url, api_key, ingest_key = credentials
            persist_fib_profit_space(
                supabase_url=url,
                supabase_publishable_key=api_key,
                radar_ingest_key=ingest_key,
                run=run,
                status=SUCCESS_STATUS,
                message=message,
                asof=run.asof_date,
            )
        payload = {
            "asof_date": run.asof_date.isoformat(),
            "status": SUCCESS_STATUS,
            "symbol_count": len(run.rows),
            "valid_count": run.valid_count,
            "ranked_count": run.ranked_count,
            "message": message,
            "top": _top_rows(run.rows),
        }
        _summary(summary_path, payload)
        print(message)
        return 0
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        print(message, file=sys.stderr)
        if not args.dry_run:
            mark_unrun(message)
        asof = state["asof"] if isinstance(state["asof"], date) else failure_asof()
        _summary(
            summary_path,
            {
                "asof_date": asof.isoformat(),
                "status": UNRUN_STATUS,
                "message": message,
                "top": [],
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
