"""Executable-entry summaries for the limit event-study backtest (logs + step summary)."""
from __future__ import annotations

from typing import Any

VARIANT_ORDER = [
    ("chase_mainline_first_board_next_open", "主线首板·次日开盘追入"),
    ("chase_first_board_next_open", "全市场首板·次日开盘追入"),
    ("chase_high_board_next_open", "高连板·次日开盘追入"),
    ("buy_mainline_broken_floor_next_open", "主线炸板回封·次日开盘买入"),
    ("buy_broken_floor_next_open", "炸板回封·次日开盘买入"),
    ("buy_close_limit_down_next_open", "收盘跌停·次日开盘买入"),
]


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def executable_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    variants = report.get("executable_variants", {}) or {}
    rows = []
    for key, label in VARIANT_ORDER:
        periods = variants.get(key)
        if not periods:
            continue
        test = periods.get("test", {})
        all_m = periods.get("all", {})
        horizons = test.get("horizons", {}) or {}
        day3 = horizons.get("day3_close", {}) or {}
        day5 = horizons.get("day5_close", {}) or {}
        rows.append(
            {
                "label": label,
                "all_entries": all_m.get("executable_entries"),
                "test_entries": test.get("executable_entries"),
                "blocked": _pct(test.get("blocked_entry_rate")),
                "gap": _pct(test.get("average_entry_gap")),
                "d3_avg": _pct(day3.get("average_return")),
                "d3_win": _pct(day3.get("win_rate")),
                "d5_avg": _pct(day5.get("average_return")),
                "d5_win": _pct(day5.get("win_rate")),
                "d5_p05": _pct(day5.get("p05_return")),
                "dd": _pct(test.get("average_worst_5d_drawdown")),
            }
        )
    return rows


def render_step_summary(report: dict[str, Any]) -> str:
    meta = report.get("metadata", {}) or {}
    lines = [
        "## 涨跌停事件研究摘要（可执行口径）",
        "",
        f"- 生成时间 `{report.get('generated_at', 'n/a')}`；"
        f"区间 `{meta.get('calendar_start', 'n/a')}` 至 `{meta.get('calendar_end', 'n/a')}`"
        f"（{meta.get('calendar_days', 'n/a')} 个交易日）",
        f"- K线标的 `{meta.get('symbols_with_klines', 'n/a')}`；"
        f"涨停触及 `{meta.get('observed_limit_touches', 'n/a')}` 次，"
        f"可用事件 `{meta.get('usable_events', 'n/a')}` 次",
        "- 口径：收盘确认后、次日开盘未封涨停才入场，收益从该开盘价起算（含成本）；样本外（test）结果。",
        "",
        "| 策略 | 全样本可成交 | 测试可成交 | 平均入场缺口 | 3日均值 | 3日胜率 "
        "| 5日均值 | 5日胜率 | 5日5%尾部 | 5日最差路径均值 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in executable_rows(report):
        lines.append(
            f"| {r['label']} | {r['all_entries']} | {r['test_entries']} | {r['gap']} | "
            f"{r['d3_avg']} | {r['d3_win']} | {r['d5_avg']} | {r['d5_win']} | "
            f"{r['d5_p05']} | {r['dd']} |"
        )
    return "\n".join(lines) + "\n"


def print_executable_summary(report: dict[str, Any]) -> None:
    print("executable entry summary (sample-out / test split):")
    for r in executable_rows(report):
        print(
            f"  {r['label']}: entries={r['test_entries']} "
            f"(all={r['all_entries']}, blocked={r['blocked']}) "
            f"avg_gap={r['gap']} day3={r['d3_avg']} (win {r['d3_win']}) "
            f"day5={r['d5_avg']} (win {r['d5_win']})"
        )
