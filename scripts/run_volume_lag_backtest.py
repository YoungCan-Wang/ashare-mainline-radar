#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ashare_mainline_radar.config import DEFAULT_THEME_CONFIG, configured_symbols, load_json
from ashare_mainline_radar.strategy_backtest import sample_breadth_symbols
from ashare_mainline_radar.tickflow import TickFlowClient, TickFlowError
from ashare_mainline_radar.volume_lag_backtest import (
    VolumeLagRules,
    render_volume_lag_backtest,
    run_volume_lag_backtest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only backtest for the volume_lag observation role.")
    parser.add_argument("--theme-config", type=Path, default=DEFAULT_THEME_CONFIG)
    parser.add_argument("--count", type=int, default=520)
    parser.add_argument("--max-symbols", type=int, default=360)
    parser.add_argument("--max-per-day", type=int, default=12)
    parser.add_argument("--output", type=Path, default=Path("reports/backtest/volume_lag_backtest.json"))
    args = parser.parse_args()

    config = load_json(args.theme_config)
    client = TickFlowClient()
    try:
        universe = client.get_universe(str(config.get("universe") or "CN_Equity_A"))
        universe_symbols = [str(symbol) for symbol in universe.get("symbols", [])]
        configured = configured_symbols(config)
        if args.max_symbols > 0:
            sampled = sample_breadth_symbols(universe_symbols, args.max_symbols)
            symbols = list(dict.fromkeys([*configured, *sampled]))[: args.max_symbols]
        else:
            symbols = list(dict.fromkeys([*configured, *universe_symbols]))
        instruments = client.get_instruments(symbols)
        klines = client.get_klines_batch(symbols, period="1d", count=args.count, adjust="none")
    except TickFlowError as exc:
        print(f"TickFlow unavailable: {exc}", file=sys.stderr)
        print(
            "Re-run with TICKFLOW_API_KEY (or free endpoint access): "
            "python3 scripts/run_volume_lag_backtest.py --count 520 --max-symbols 360",
            file=sys.stderr,
        )
        return 2

    rules = VolumeLagRules(max_per_day=args.max_per_day)
    report = run_volume_lag_backtest(klines, instruments, rules=rules)
    report["universe"] = {
        "requested_symbols": len(symbols),
        "instruments": len(instruments),
        "klines": len(klines),
        "adjust": "none",
        "tickflow": client.source_label,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = args.output.with_suffix(".md")
    markdown = render_volume_lag_backtest(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Wrote {markdown_path}")
    verdict = report["verdict"]
    low = report["strategies"]["volume_lag_low_base"]["test"]["next_open"].get("5", {})
    high = report["strategies"]["high_base_lag"]["test"]["next_open"].get("5", {})
    amount = report["strategies"]["amount_topn"]["test"]["next_open"].get("5", {})
    print(f"verdict={verdict['decision']}")
    print(f"low_base test next_open_5 trades={low.get('trades')} mean={low.get('mean_return')}")
    print(f"high_base test next_open_5 trades={high.get('trades')} mean={high.get('mean_return')}")
    print(f"amount_topn test next_open_5 trades={amount.get('trades')} mean={amount.get('mean_return')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
