#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ashare_mainline_radar.config import DEFAULT_THEME_CONFIG, configured_symbols, load_json
from ashare_mainline_radar.limit_up_backtest import (
    build_limit_up_backtest_report,
    collect_limit_down_events,
    collect_limit_up_events,
    prepare_limit_event_context,
    render_limit_up_backtest,
)
from ashare_mainline_radar.tickflow import TickFlowClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest A-share price-limit ceiling and floor events.")
    parser.add_argument("--theme-config", type=Path, default=DEFAULT_THEME_CONFIG)
    parser.add_argument("--count", type=int, default=1200)
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--warmup-days", type=int, default=80)
    parser.add_argument("--output", type=Path, default=Path("reports/backtest/limit_up_backtest.json"))
    args = parser.parse_args()

    config = load_json(args.theme_config)
    client = TickFlowClient()
    universe = client.get_universe(str(config.get("universe") or "CN_Equity_A"))
    universe_symbols = [str(symbol) for symbol in universe.get("symbols", [])]
    if args.max_symbols > 0:
        universe_symbols = universe_symbols[: args.max_symbols]
    symbols = list(dict.fromkeys([*universe_symbols, *configured_symbols(config)]))
    instruments = client.get_instruments(symbols)
    klines = client.get_klines_batch(symbols, period="1d", count=args.count, adjust="none")
    event_context = prepare_limit_event_context(config, klines, instruments, args.warmup_days)
    events, metadata = collect_limit_up_events(
        config,
        klines,
        instruments,
        warmup_days=args.warmup_days,
        event_context=event_context,
    )
    limit_down_events, limit_down_metadata = collect_limit_down_events(
        config,
        klines,
        instruments,
        warmup_days=args.warmup_days,
        event_context=event_context,
    )
    report = build_limit_up_backtest_report(
        events,
        {**metadata, **limit_down_metadata},
        limit_down_events,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = args.output.with_suffix(".md")
    markdown_path.write_text(render_limit_up_backtest(report), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Wrote {markdown_path}")
    strict = report["variants"]["mainline_first_board_close_sealed_conditional"]["test"]
    print(
        "mainline first-board test: "
        f"signals={strict['signals']}, "
        f"next_open={strict['horizons']['next_open']['average_return']}, "
        f"day5={strict['horizons']['day5_close']['average_return']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
