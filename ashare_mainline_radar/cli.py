from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import DEFAULT_INTEL_CONFIG, DEFAULT_THEME_CONFIG, load_json
from .engine import MainlineRadar
from .feishu import FeishuStatus, build_feishu_card, post_feishu_card, write_feishu_status
from .report import write_report
from .tickflow import TickFlowClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate an A-share market mainline radar report.")
    parser.add_argument("--mode", choices=["curated", "universe"], default=os.getenv("MAINLINE_RADAR_MODE", "curated"))
    parser.add_argument("--max-symbols", type=int, default=int(os.getenv("MAINLINE_MAX_SYMBOLS", "0")))
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument("--theme-config", type=Path, default=DEFAULT_THEME_CONFIG)
    parser.add_argument("--intel-config", type=Path, default=DEFAULT_INTEL_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/latest"))
    parser.add_argument("--period", default="1d")
    parser.add_argument("--adjust", default="forward")
    parser.add_argument("--leader-limit", type=int, default=25)
    parser.add_argument(
        "--backtest-hold-days",
        type=int,
        default=int(os.getenv("MAINLINE_HOLD_DAYS", "15")),
        help="Expected holding period in trading days; defaults to 15 for a 10-20 day style.",
    )
    parser.add_argument("--strong-stock-limit", type=int, default=12)
    parser.add_argument("--accumulation-limit", type=int, default=12)
    parser.add_argument("--send-feishu", action="store_true", help="Send a compact report to FEISHU_WEBHOOK_URL.")
    parser.add_argument("--feishu-webhook-url", default=os.getenv("FEISHU_WEBHOOK_URL"))
    parser.add_argument("--fail-on-feishu-error", action="store_true")
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
        backtest_hold_days=args.backtest_hold_days,
        strong_stock_limit=args.strong_stock_limit,
        accumulation_limit=args.accumulation_limit,
    )
    markdown_path, json_path = write_report(report, args.output_dir)
    feishu_card = build_feishu_card(report)
    feishu_card_path = args.output_dir / "feishu_card.json"
    feishu_card_path.write_text(json.dumps(feishu_card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {markdown_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {feishu_card_path}")
    if report.themes:
        top = report.themes[0]
        print(f"Top mainline: {top.name} / {top.status} / score={top.score:.1f}")
    if report.strong_stocks.candidates:
        top_stock = report.strong_stocks.candidates[0]
        print(f"Top strong stock: {top_stock.name} {top_stock.symbol} / score={top_stock.score:.1f}")
    if report.accumulation.candidates:
        top_accumulation = report.accumulation.candidates[0]
        print(
            "Top accumulation stock: "
            f"{top_accumulation.name} {top_accumulation.symbol} / score={top_accumulation.score:.1f}"
        )
    if args.send_feishu:
        if not args.feishu_webhook_url:
            print("FEISHU_WEBHOOK_URL is not set; skipped Feishu notification.")
            write_feishu_status(args.output_dir / "notification_status.json", FeishuStatus(status="skipped", message="FEISHU_WEBHOOK_URL is not set"))
        else:
            status = post_feishu_card(args.feishu_webhook_url, feishu_card)
            write_feishu_status(args.output_dir / "notification_status.json", status)
            if status.status == "sent":
                print("Sent Feishu notification.")
            else:
                print(f"Feishu notification failed: code={status.code} message={status.message}")
                if args.fail_on_feishu_error:
                    return 2
    return 0
