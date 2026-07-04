from __future__ import annotations

import json
from pathlib import Path

from .models import (
    AccumulationCandidate,
    DataSourceStatus,
    IntelItem,
    MarketPulse,
    RadarReport,
    StrongStockCandidate,
    NextBuyPlan,
    ThemeBuyGroup,
    SymbolSnapshot,
    ThemeSnapshot,
    pct,
)


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
        f"{pct(theme.breadth_20d)} | {theme.catalyst_count} | {theme.policy_catalyst_count} | {theme.policy_score:.1f} | {vehicles} |"
    )


def _pulse_row(rank: int, pulse: MarketPulse) -> str:
    leaders = ", ".join(f"{item.name} `{item.symbol}`" for item in pulse.leaders[:3]) if pulse.leaders else "-"
    return (
        f"| {rank} | {pulse.name} | {pulse.status} | {pulse.score:.1f} | {pulse.members} | "
        f"{pct(pulse.avg_ret_5d)} | {pct(pulse.avg_ret_20d)} | {_ratio(pulse.amount_heat)} | "
        f"{pct(pulse.positive_20d)} | {leaders} |"
    )


def _source_row(source: DataSourceStatus) -> str:
    message = (source.message or "").replace("|", "/")
    return f"| {source.name} | {source.kind} | {source.status} | {source.items} | {message} |"


def _strong_stock_row(rank: int, item: StrongStockCandidate) -> str:
    backtest = item.backtest
    signals = 0 if backtest is None else backtest.signals
    win_rate = None if backtest is None else backtest.win_rate
    avg_return = None if backtest is None else backtest.avg_return
    worst_return = None if backtest is None else backtest.worst_return
    drawdown = None if backtest is None else backtest.avg_max_drawdown
    return (
        f"| {rank} | {item.theme} | {item.name} `{item.symbol}` | {item.status} | {item.score:.1f} | "
        f"{pct(item.ret_5d)} | {pct(item.ret_20d)} | {_ratio(item.amount_ratio)} | "
        f"{signals} | {pct(win_rate)} | {pct(avg_return)} | {pct(worst_return)} | {pct(drawdown)} |"
    )


def _next_buy_row(rank: int, item: NextBuyPlan) -> str:
    return (
        f"| {rank} | {item.name} `{item.symbol}` | {item.theme} | {item.decision} | "
        f"{item.priority_score:.1f} | {_fmt(item.last_close)} | {item.entry_plan} | {item.invalidation} |"
    )


def _theme_buy_group_row(rank: int, group: ThemeBuyGroup) -> str:
    plans = "；".join(
        f"{idx}. {plan.name} `{plan.symbol}` {plan.decision}({plan.priority_score:.1f})"
        for idx, plan in enumerate(group.plans, start=1)
    )
    return f"| {rank} | {group.theme} | {group.theme_status} | {plans or '-'} |"


def _accumulation_row(rank: int, item: AccumulationCandidate) -> str:
    themes = ", ".join(item.themes) if item.themes else "未映射"
    return (
        f"| {rank} | {themes} | {item.name} `{item.symbol}` | {item.status} | {item.score:.1f} | "
        f"{pct(item.range_position_60d)} | {pct(item.drawdown_60d)} | {pct(item.ret_5d)} | {pct(item.ret_20d)} | "
        f"{_ratio(item.amount_ratio_5_20)} | {_ratio(item.amount_ratio_10_30)} | {pct(item.ma20_distance)} | "
        f"{item.entry_plan} | {item.invalidation} |"
    )


def _policy_signal_row(rank: int, theme: str, status: str, score: float, count: int, sources: list[str], evidence: list[str]) -> str:
    source_text = ", ".join(sources[:3]) if sources else "-"
    evidence_text = "；".join(evidence[:3]) if evidence else "-"
    return f"| {rank} | {theme} | {status} | {score:.1f} | {count} | {source_text} | {evidence_text} |"


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
    lines.append("| 排名 | 主线 | 状态 | 强度 | 成员 | 5日均涨幅 | 20日均涨幅 | 成交热度 | 20日广度 | 新闻/研报催化 | 政策条数 | 政策分 | 参与载体 |")
    lines.append("| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
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

    if report.policy_signals.signals:
        lines.append("## 政策催化雷达")
        lines.append("")
        lines.append(
            f"本次抓到官方政策条目 {report.policy_signals.total_policy_items} 条，"
            f"其中 {report.policy_signals.matched_policy_items} 条命中主题关键词。"
        )
        lines.append("")
        lines.append("| 排名 | 主线 | 主线状态 | 政策分 | 政策条数 | 来源 | 代表政策线索 |")
        lines.append("| ---: | --- | --- | ---: | ---: | --- | --- |")
        for rank, signal in enumerate(report.policy_signals.signals[:8], start=1):
            evidence = [item.title for item in signal.evidence]
            lines.append(
                _policy_signal_row(
                    rank,
                    signal.theme,
                    signal.theme_status,
                    signal.score,
                    signal.item_count,
                    signal.sources,
                    evidence,
                )
            )
        lines.append("")
        for note in report.policy_signals.notes:
            lines.append(f"- {note}")
        lines.append("")

    if report.market_pulses:
        lines.append("## 市场环境与外围映射")
        lines.append("")
        lines.append("| 排名 | 环境组 | 状态 | 强度 | 成员 | 5日均涨幅 | 20日均涨幅 | 成交热度 | 20日广度 | 代表标的 |")
        lines.append("| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
        for rank, pulse in enumerate(report.market_pulses, start=1):
            lines.append(_pulse_row(rank, pulse))
        lines.append("")
        best_pulse = report.market_pulses[0]
        lines.append(f"环境结论：**{best_pulse.name}** 当前最强，状态为 **{best_pulse.status}**，证据包括：{'; '.join(best_pulse.evidence)}。")
        lines.append("")

    if report.next_buy.primary:
        primary = report.next_buy.primary
        lines.append("## 下一笔买入候选")
        lines.append("")
        lines.append(
            f"系统下一笔优先候选：**{primary.name} `{primary.symbol}`**，主线 **{primary.theme}**，"
            f"决策：**{primary.decision}**，优先级 {primary.priority_score:.1f}。"
        )
        lines.append("")
        lines.append("| 排名 | 标的 | 主线 | 决策 | 优先级 | 最新收盘 | 触发/参与条件 | 失效条件 |")
        lines.append("| ---: | --- | --- | --- | ---: | ---: | --- | --- |")
        for rank, item in enumerate([primary, *report.next_buy.alternatives], start=1):
            lines.append(_next_buy_row(rank, item))
        lines.append("")
        if report.next_buy.by_theme:
            lines.append("分主线候选：系统不是只看第一主线；命中条件的活跃主线会保留自己的顺势首选和备选。")
            lines.append("")
            lines.append("| 排名 | 主线 | 状态 | 顺势候选 |")
            lines.append("| ---: | --- | --- | --- |")
            for rank, group in enumerate(report.next_buy.by_theme[:6], start=1):
                lines.append(_theme_buy_group_row(rank, group))
            lines.append("")
        lines.append("证据：")
        for item in primary.evidence:
            lines.append(f"- {item}")
        lines.append("")
        lines.append(f"仓位提示：{primary.position_note}")
        lines.append("")
        for item in primary.risk_notes:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("## 低位资金介入候选")
    lines.append("")
    lines.append("这张表不是顺势追强榜；它寻找仍处在60日中低位、成交额均线开始抬升、短线跌势收敛的股票，适合作为观察/试错池。")
    lines.append("")
    if report.accumulation.candidates:
        lines.append("| 排名 | 主题 | 标的 | 状态 | 评分 | 60日位置 | 距60日高点 | 5日 | 20日 | 成交5/20 | 成交10/30 | 距20日线 | 触发/参与条件 | 失效条件 |")
        lines.append("| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |")
        for rank, item in enumerate(report.accumulation.candidates[:12], start=1):
            lines.append(_accumulation_row(rank, item))
        lines.append("")
        for item in report.accumulation.candidates[:5]:
            if item.reasons:
                lines.append(f"- **{item.name} `{item.symbol}`**：{'；'.join(item.reasons)}。")
    else:
        lines.append("- 当前扫描范围内没有同时满足低位、放量和止跌条件的股票。")
    if report.accumulation.notes:
        lines.append("")
        for note in report.accumulation.notes:
            lines.append(f"- {note}")
    lines.append("")

    if report.strong_stocks.candidates:
        lines.append("## 强势个股与历史回测")
        lines.append("")
        lines.append(
            f"候选来自当前主线：{', '.join(report.strong_stocks.selected_themes)}。"
            f" 回测口径：信号日后下一交易日开盘进入，固定持有 {report.strong_stocks.hold_days} 个交易日后按收盘退出。"
        )
        lines.append("")
        lines.append("| 排名 | 主线 | 标的 | 当前状态 | 综合分 | 5日 | 20日 | 成交热度 | 信号数 | 胜率 | 平均收益 | 最差收益 | 平均最大回撤 |")
        lines.append("| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for rank, item in enumerate(report.strong_stocks.candidates[:12], start=1):
            lines.append(_strong_stock_row(rank, item))
        lines.append("")
        for item in report.strong_stocks.candidates[:5]:
            if item.reasons:
                lines.append(f"- **{item.name} `{item.symbol}`**：{'；'.join(item.reasons)}。")
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

    lines.append("## 数据源状态")
    lines.append("")
    lines.append("| 数据源 | 类型 | 状态 | 条目 | 说明 |")
    lines.append("| --- | --- | --- | ---: | --- |")
    for source in report.source_statuses:
        lines.append(_source_row(source))
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
