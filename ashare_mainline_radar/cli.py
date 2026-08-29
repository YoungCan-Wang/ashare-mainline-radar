from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import DEFAULT_INTEL_CONFIG, DEFAULT_THEME_CONFIG, load_json
from .engine import MainlineRadar
from .feishu import FeishuStatus, build_feishu_card, build_shadow_feishu_card, post_feishu_card, write_feishu_status
from .next_buy import overlay_triggered_working_orders, select_triggered_working_orders
from .paper_trading import PaperTradeRefreshStatus, refresh_paper_trades
from .report import write_report
from .shadow_account import ShadowRefreshStatus, empty_snapshot, refresh_shadow_account
from .storage import persist_report
from .tickflow import TickFlowClient
from .workflow_frequency import session_as_of


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
    parser.add_argument("--as-of", help="Point-in-time cutoff in YYYY-MM-DD; excludes later market, news, and financial data.")
    parser.add_argument("--send-feishu", action="store_true", help="Send a compact report to FEISHU_WEBHOOK_URL.")
    parser.add_argument("--feishu-webhook-url", default=os.getenv("FEISHU_WEBHOOK_URL"))
    parser.add_argument(
        "--shadow-feishu-webhook-url",
        default=os.getenv("SHADOW_FEISHU_WEBHOOK_URL"),
        help="Optional webhook for the shadow cash-book card; defaults to FEISHU_WEBHOOK_URL.",
    )
    parser.add_argument(
        "--dashboard-public-url",
        default=os.getenv("DASHBOARD_PUBLIC_URL"),
        help="Public dashboard URL shown as a Feishu card button.",
    )
    parser.add_argument("--fail-on-feishu-error", action="store_true")
    parser.add_argument(
        "--storage-backend",
        choices=["auto", "supabase", "artifact", "none"],
        default=os.getenv("RADAR_STORAGE_BACKEND", "auto"),
        help="Persist normalized run, theme, and symbol snapshots. Auto uses Supabase when configured.",
    )
    parser.add_argument("--fail-on-storage-error", action="store_true")
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
    as_of = args.as_of or session_as_of(datetime.now(timezone.utc)).isoformat()
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
        as_of=as_of,
    )
    active_themes = {
        theme.name for theme in report.themes[:3] if theme.status in {"主线成立", "主线候选"}
    }
    paper_klines = {}
    paper_plans: list[dict] = []
    try:
        paper_status = refresh_paper_trades(
            active_themes, client=client, kline_out=paper_klines, plans_out=paper_plans
        )
    except Exception as exc:
        paper_status = PaperTradeRefreshStatus("failed", 0, 0, 0, f"{type(exc).__name__}: {exc}")
    overlay_triggered_working_orders(report.next_buy, paper_plans)
    markdown_path, json_path = write_report(report, args.output_dir)
    feishu_card = build_feishu_card(report, dashboard_url=args.dashboard_public_url)
    feishu_card_path = args.output_dir / "feishu_card.json"
    feishu_card_path.write_text(json.dumps(feishu_card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {markdown_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {feishu_card_path}")
    storage_status = persist_report(report, args.output_dir, backend=args.storage_backend)
    print(
        f"Storage: {storage_status.status} via {storage_status.backend}; "
        f"themes={storage_status.theme_records} symbols={storage_status.symbol_records}"
    )
    (args.output_dir / "paper_trade_status.json").write_text(
        json.dumps(paper_status.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Paper trades: {paper_status.status}; checked={paper_status.plans_checked} "
        f"updated={paper_status.plans_updated} events={paper_status.events_written}"
    )
    try:
        shadow_status = refresh_shadow_account(
            as_of=report.data_as_of,
            client=client,
            klines=paper_klines,
        )
    except Exception as exc:
        shadow_status = ShadowRefreshStatus(
            "failed",
            0,
            0,
            0,
            f"{type(exc).__name__}: {exc}",
            empty_snapshot(report.data_as_of),
        )
    shadow_card = build_shadow_feishu_card(
        shadow_status.snapshot,
        status=shadow_status.status,
        message=shadow_status.message,
        working_orders=select_triggered_working_orders(paper_plans),
    )
    shadow_card_path = args.output_dir / "shadow_card.json"
    shadow_card_path.write_text(json.dumps(shadow_card, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "shadow_status.json").write_text(
        json.dumps(shadow_status.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "shadow_account.json").write_text(
        json.dumps(shadow_status.snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"Wrote {shadow_card_path}")
    print(
        f"Shadow account: {shadow_status.status}; fills={shadow_status.fills} "
        f"blocked={shadow_status.blocked} events={shadow_status.events_written}"
    )
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
            write_feishu_status(
                args.output_dir / "shadow_notification_status.json",
                FeishuStatus(status="skipped", message="FEISHU_WEBHOOK_URL is not set"),
            )
        else:
            status = post_feishu_card(args.feishu_webhook_url, feishu_card)
            write_feishu_status(args.output_dir / "notification_status.json", status)
            if status.status == "sent":
                print("Sent Feishu notification.")
            else:
                print(f"Feishu notification failed: code={status.code} message={status.message}")
            shadow_webhook = args.shadow_feishu_webhook_url or args.feishu_webhook_url
            shadow_notify = post_feishu_card(shadow_webhook, shadow_card)
            write_feishu_status(args.output_dir / "shadow_notification_status.json", shadow_notify)
            if shadow_notify.status == "sent":
                print(f"Sent shadow account Feishu notification ({shadow_status.status}).")
            else:
                print(
                    f"Shadow Feishu notification failed: code={shadow_notify.code} message={shadow_notify.message}"
                )
            if args.fail_on_feishu_error and (status.status != "sent" or shadow_notify.status != "sent"):
                return 2
    if args.fail_on_storage_error and storage_status.status == "failed":
        return 3
    return 0
