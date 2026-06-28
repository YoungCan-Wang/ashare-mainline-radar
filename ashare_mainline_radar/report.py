from __future__ import annotations

import json
from pathlib import Path

from .models import IntelItem, RadarReport, SymbolSnapshot, ThemeSnapshot, pct


def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}x"


def _symbol_cell(snapshot: SymbolSnapshot) -> str:
    themes = ",".join(snapshot.themes) if snapshot.themes else "未映射"
    return f"{snapshot.name} `{snapshot.symbol}` ({themes})"


def _leader_table(leaders: list[SymbolSnapshot]) -> list[str]:
    lines = [
        "| 标的 | 状态 | 强度 | 5日 | 20日 | 成交热度 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for item in leaders:
        lines.append(
            f"| {_symbol_cell(item)} | {item.status} | {item.score:.1f} | {pct(item.ret_5d)} | {pct(item.ret_20d)} | {_ratio(item.amount_ratio)} |"
        )
    return lines


def _theme_row(rank: int, theme: ThemeSnapshot) -> str:
    vehicles = ", ".join(f"`{item}`" for item in theme.vehicles[:4]) if theme.vehicles else "-"
    return (
        f"| {rank} | {theme.name} | {theme.status} | {theme.score:.1f} | {theme.members} | "
        f"{pct(theme.avg_ret_5d)} | {pct(theme.avg_ret_20d)} | {_ratio(theme.amount_heat)} | "
        f"{pct(theme.breadth_20d)} | {theme.catalyst_count} | {vehicles} |"
    )


def _participation_note(theme: ThemeSnapshot) -> str:
    if theme.status == "主线成立":
        return "参与思路：优先等龙头或 ETF 在强势均线附近缩量回踩、再放量转强；若主题广度跌破半数或龙头连续放量滞涨，降低仓位。"
    if theme.status == "主线候选":
        return "参与思路：先放入观察池，等待指数环境配合和主题内 2-3 个龙头同步突破；没有广度确认前避免重仓追高。"
    if theme.status == "轮动观察":
        return "参与思路：按短线轮动处理，只跟踪最强载体；若成交热度无法维持，视作反弹而非主线。"
    return "参与思路：暂不作为主线参与，只保留新闻或政策催化观察。"


def render_markdown(report: RadarReport) -> str:
    lines: list[str] = []
    lines.append("# A股市场主线雷达")
    lines.append("")
    lines.append(f"- 生成时间：`{report.generated_at}`")
    lines.append(f"- 行情日期：`{report.data_as_of or 'n/a'}`")
    lines.append(f"- 扫描模式：`{report.mode}`")
    lines.append(f"- 标的池：`{report.universe}`")
    lines.append(f"- 有效标的数：`{report.scanned_symbols}`")
    lines.append(f"- 数据源：{report.data_source}")
    lines.append("")
    lines.append("## 主线排序")
    lines.append("")
    lines.append("| 排名 | 主线 | 状态 | 强度 | 成员 | 5日均涨幅 | 20日均涨幅 | 成交热度 | 20日广度 | 催化 | 参与载体 |")
    lines.append("| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for rank, theme in enumerate(report.themes[:12], start=1):
        lines.append(_theme_row(rank, theme))
    lines.append("")

    if report.themes:
        top = report.themes[0]
        lines.append("## 今日结论")
        lines.append("")
        lines.append(
            f"当前雷达最强主线是 **{top.name}**，状态为 **{top.status}**，强度 {top.score:.1f}。"
            f" 证据包括：{'; '.join(top.evidence)}。"
        )
        lines.append("")
        lines.append(_participation_note(top))
        lines.append("")

    lines.append("## 主线拆解")
    lines.append("")
    for theme in report.themes[:6]:
        lines.append(f"### {theme.name} - {theme.status} ({theme.score:.1f})")
        lines.append("")
        lines.append(_participation_note(theme))
        lines.append("")
        lines.extend(_leader_table(theme.leaders))
        lines.append("")
        if theme.evidence:
            lines.append("证据：")
            for item in theme.evidence:
                lines.append(f"- {item}")
            lines.append("")

    lines.append("## 全市场强势带")
    lines.append("")
    lines.extend(_leader_table(report.leader_tape[:20]))
    lines.append("")

    if report.market_watchlist:
        lines.append("## 宽基/外围观察")
        lines.append("")
        lines.extend(_leader_table(report.market_watchlist))
        lines.append("")

    matched_intel = [item for item in report.intel_items if item.matched_themes]
    lines.append("## 新闻/宏观/研报线索")
    lines.append("")
    if matched_intel:
        for item in matched_intel[:20]:
            url = f" [{item.url}]({item.url})" if item.url and item.url.startswith("http") else ""
            themes = ", ".join(item.matched_themes)
            lines.append(f"- **{themes}** | {item.source}: {item.title}{url}")
    else:
        lines.append("- 暂无命中主题关键词的情报项；可把研报摘要或纪要放入 `data/research_reports/inbox/` 后重新运行。")
    lines.append("")

    lines.append("## 风险提示")
    lines.append("")
    for warning in report.warnings:
        lines.append(f"- {warning}")
    lines.append("- 实盘参与前，请额外检查指数环境、仓位上限、止损条件、流动性和重大公告。")
    lines.append("")
    return "\n".join(lines)


def write_report(report: RadarReport, output_dir: str | Path) -> tuple[Path, Path]:
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)
    markdown_path = output_path / "mainline_report.md"
    json_path = output_path / "mainline_report.json"
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return markdown_path, json_path
