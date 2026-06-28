from __future__ import annotations

import argparse
import os
from pathlib import Path

from .config import DEFAULT_INTEL_CONFIG, DEFAULT_THEME_CONFIG, load_json
from .engine import MainlineRadar
from .report import write_report
from .tickflow import TickFlowClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate an A-share market mainline radar report.")
    parser.add_argument("--mode", choices=["curated", "universe"], default=os.getenv("MAINLINE_RADAR_MODE", "curated"))
    parser.add_argument("--max-symbols", type=int, default=int(os.getenv("MAINLINE_MAX_SYMBOLS", "0")))
    parser.add_argument("--lookback-days", type=int, default=80)
    parser.add_argument("--theme-config", type=Path, default=DEFAULT_THEME_CONFIG)
    parser.add_argument("--intel-config", type=Path, default=DEFAULT_INTEL_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/latest"))
    parser.add_argument("--period", default="1d")
    parser.add_argument("--adjust", default="forward")
    parser.add_argument("--leader-limit", type=int, default=25)
    parser.add_argument("--tickflow-base-url", default=os.getenv("TICKFLOW_BASE_URL"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = TickFlowClient(base_url=args.tickflow_base_url)
    radar = MainlineRadar(
        client=client,
        theme_config=load_json(args.theme_config),
        intel_config=load_json(args.intel_config),
    )
    report = radar.run(
        mode=args.mode,
        max_symbols=args.max_symbols,
        lookback_days=args.lookback_days,
        period=args.period,
        adjust=args.adjust,
        leader_limit=args.leader_limit,
    )
    markdown_path, json_path = write_report(report, args.output_dir)
    print(f"Wrote {markdown_path}")
    print(f"Wrote {json_path}")
    if report.themes:
        top = report.themes[0]
        print(f"Top mainline: {top.name} / {top.status} / score={top.score:.1f}")
    return 0
