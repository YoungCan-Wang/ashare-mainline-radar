#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ashare_mainline_radar.config import DEFAULT_THEME_CONFIG, configured_symbols, load_json
from ashare_mainline_radar.cross_market import cross_market_symbols
from ashare_mainline_radar.strategy_backtest import (
    render_strategy_backtest,
    run_strategy_backtest,
    sample_breadth_symbols,
)
from ashare_mainline_radar.tickflow import TickFlowClient, TickFlowError


def main() -> int:
    parser = argparse.ArgumentParser(description="Run point-in-time A-share mainline strategy backtest.")
    parser.add_argument("--theme-config", type=Path, default=DEFAULT_THEME_CONFIG)
    parser.add_argument("--count", type=int, default=1800)
    parser.add_argument("--breadth-symbols", type=int, default=600)
    parser.add_argument("--output", type=Path, default=Path("reports/backtest/strategy_backtest.json"))
    args = parser.parse_args()

    config = load_json(args.theme_config)
    client = TickFlowClient()
    a_symbols = configured_symbols(config)
    universe = client.get_universe(str(config.get("universe") or "CN_Equity_A"))
    breadth_symbols = sample_breadth_symbols(
        [str(symbol) for symbol in universe.get("symbols", [])],
        args.breadth_symbols,
    )
    a_symbols = list(dict.fromkeys([*a_symbols, *breadth_symbols]))
    hk_symbols = cross_market_symbols(config)
    a_instruments = client.get_instruments(a_symbols)
    hk_instruments = client.get_instruments(hk_symbols)
    a_klines = client.get_klines_batch(a_symbols, period="1d", count=args.count, adjust="forward")
    hk_klines = client.get_klines_batch(hk_symbols, period="1d", count=args.count, adjust="forward")
    strategy_symbols = configured_symbols(config)
    raw_fundamentals: dict = {}
    if client.api_key and strategy_symbols:
        try:
            raw_fundamentals = client.get_financial_metrics(strategy_symbols)
        except TickFlowError as exc:
            print(f"Warning: financial metrics unavailable for fund_block_drag challenger: {exc}")
    report = run_strategy_backtest(
        config,
        a_klines,
        a_instruments,
        hk_klines,
        hk_instruments,
        breadth_symbols=set(breadth_symbols),
        raw_fundamentals=raw_fundamentals,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = args.output.with_suffix(".md")
    markdown_path.write_text(render_strategy_backtest(report), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Wrote {markdown_path}")
    print(report.verdict)
    for variant in report.variants:
        if variant.hold_days == 15:
            metric = variant.test
            avg = "n/a" if metric.avg_return is None else f"{metric.avg_return * 100:.2f}%"
            print(f"{variant.name}: test trades={metric.trades}, avg={avg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
