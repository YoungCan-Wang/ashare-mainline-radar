from __future__ import annotations

import json
from pathlib import Path

from .models import (
    AccumulationCandidate,
    DataSourceStatus,
    FundamentalSnapshot,
    GoldenPitCandidate,
    MarketPulse,
    MonthlyBaseCandidate,
    NextBuyPlan,
    RadarReport,
    StrongStockCandidate,
    SymbolSnapshot,
    TargetPriceEstimate,
    ThemeBuyGroup,
    ThemeLifecycleSignal,
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
        f"{pct(theme.breadth_20d)} | {theme.price_phase} | {_fmt(theme.crowding_score, 1)} | "
        f"{theme.catalyst_count} | {theme.policy_catalyst_count} | {theme.policy_score:.1f} | {vehicles} |"
    )


def _theme_lifecycle_row(rank: int, signal: ThemeLifecycleSignal) -> str:
    return (
        f"| {rank} | {signal.theme} | {signal.stage} | {signal.score:.1f} | "
        f"{signal.started_at or '-'} | {signal.confirmed_at or '-'} | {signal.stage_since} | "
        f"{pct(signal.breadth_5d)} | {pct(signal.breadth_20d)} | {_ratio(signal.amount_heat)} | "
        f"{pct(signal.relative_strength_5d)} | {signal.independence_status} {signal.independent_score:.1f} | "
        f"{signal.action} |"
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
        f"{pct(item.ret_5d)} | {pct(item.ret_20d)} | {_ratio(item.amount_ratio)} | {item.fundamental_status} | {_fmt(item.fundamental_score, 1)} | "
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
    return (
        f"| {rank} | {group.theme} | {group.theme_status} | {group.lifecycle_stage} | "
        f"{group.independence_status} | {plans or group.note or '-'} |"
    )


def _accumulation_row(rank: int, item: AccumulationCandidate) -> str:
    themes = ", ".join(item.themes) if item.themes else "未映射"
    return (
        f"| {rank} | {themes} | {item.name} `{item.symbol}` | {item.status} | {item.score:.1f} | "
        f"{pct(item.range_position_60d)} | {pct(item.drawdown_60d)} | {pct(item.ret_5d)} | {pct(item.ret_20d)} | "
        f"{_ratio(item.amount_ratio_5_20)} | {_ratio(item.amount_ratio_10_30)} | {pct(item.ma20_distance)} | "
        f"{item.fundamental_status} | {_fmt(item.fundamental_score, 1)} | "
        f"{item.entry_plan} | {item.invalidation} |"
    )


def _golden_pit_row(rank: int, item: GoldenPitCandidate) -> str:
    return (
        f"| {rank} | {item.name} `{item.symbol}` | {item.theme} | {item.stage} | {item.score:.1f} | "
        f"{pct(item.drawdown_from_20d_high)} | {pct(item.ret_1d)} | {pct(item.relative_1d)} | "
        f"{_ratio(item.amount_ratio_1_5)} | {item.fundamental_status} | {item.action} | "
        f"{item.confirmation} | {item.invalidation} |"
    )


def _monthly_base_row(rank: int, item: MonthlyBaseCandidate) -> str:
    themes = ", ".join(item.themes) if item.themes else "未映射"
    return (
        f"| {rank} | {item.name} `{item.symbol}` | {themes} | {item.stage} | {item.score:.1f} | "
        f"{item.box_months} | {_fmt(item.box_low)}-{_fmt(item.box_high)} | {pct(item.box_width)} | "
        f"{pct(item.box_position)} | {_ratio(item.amount_contraction)} | {_fmt(item.prior_peak_multiple)}x | "
        f"{item.action} | {item.confirmation} | {item.invalidation} |"
    )


def _fundamental_row(rank: int, item: FundamentalSnapshot) -> str:
    return (
        f"| {rank} | `{item.symbol}` | {item.period_end} | {item.status} | {item.score:.1f} | "
        f"{_fmt(item.revenue_yoy, 1)}% | {_fmt(item.net_income_yoy, 1)}% | {_fmt(item.roe, 1)}% | "
        f"{_fmt(item.ocfps)} | {_fmt(item.price_to_book)}x | {_fmt(item.revenue_yoy_change, 1)}pct | "
        f"{_fmt(item.net_income_yoy_change, 1)}pct |"
    )


def _policy_signal_row(
    rank: int, theme: str, status: str, score: float, count: int, sources: list[str], evidence: list[str]
) -> str:
    source_text = ", ".join(sources[:3]) if sources else "-"
    evidence_text = "；".join(evidence[:3]) if evidence else "-"
    return f"| {rank} | {theme} | {status} | {score:.1f} | {count} | {source_text} | {evidence_text} |"


def _research_target_text(item: TargetPriceEstimate) -> str:
    if not item.research_targets:
        return "-"
    refs = []
    for ref in item.research_targets[:2]:
        target = (
            f"{_fmt(ref.target_low)}"
            if ref.target_low == ref.target_high
            else f"{_fmt(ref.target_low)}-{_fmt(ref.target_high)}"
        )
        refs.append(f"{ref.source}: {target}")
    return "；".join(refs)


def _target_price_row(rank: int, item: TargetPriceEstimate) -> str:
    target = f"{_fmt(item.target_low)}-{_fmt(item.target_high)}"
    upside = f"{pct(item.upside_low)}-{pct(item.upside_high)}"
    rr_low = "n/a" if item.reward_risk_low is None else f"{item.reward_risk_low:.2f}"
    rr_high = "n/a" if item.reward_risk_high is None else f"{item.reward_risk_high:.2f}"
    return (
        f"| {rank} | {item.candidate_type} | {item.name} `{item.symbol}` | {item.theme} | {item.basis} | "
        f"{item.horizon} | {_fmt(item.last_close)} | {target} | {upside} | {_fmt(item.stop_price)} | "
        f"{pct(item.downside_to_stop)} | {rr_low}-{rr_high} | {item.confidence} | {_research_target_text(item)} |"
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
    lines.append("## 今日交易闸门")
    lines.append("")
    lines.append(
        f"**{report.trading_gate.state}**（{report.trading_gate.level}，环境分 {report.trading_gate.score:.1f}）"
    )
    lines.append("")
    for reason in report.trading_gate.reasons:
        lines.append(f"- {reason}")
    lines.append(f"- 允许动作：{'；'.join(report.trading_gate.allowed_actions)}")
    lines.append("")
    lines.append(f"指数结构：**{report.market_structure.status}**，确认分 {report.market_structure.score:.1f}")
    for item in report.market_structure.evidence:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 主线排序")
    lines.append("")
    lines.append(
        "| 排名 | 主线 | 状态 | 强度 | 成员 | 5日均涨幅 | 20日均涨幅 | 成交热度 | 20日广度 | 价格阶段 | 拥挤代理 | 新闻/研报催化 | 政策条数 | 政策分 | 参与载体 |"
    )
    lines.append(
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- |"
    )
    for rank, theme in enumerate(report.themes[:12], start=1):
        lines.append(_theme_row(rank, theme))
    lines.append("")

    lines.append("## 主线生命周期预警")
    lines.append("")
    lines.append("该状态由最近日K回放生成；风险闸门只约束参与动作，不会隐藏板块启动或回踩。")
    lines.append("")
    if report.theme_lifecycle.signals:
        lines.append(
            "| 排名 | 主线 | 当前阶段 | 强度 | 本轮启动 | 主线确认 | 阶段始于 | "
            "5日广度 | 20日广度 | 成交热度 | 相对全市场5日 | 独立状态 | 当前动作 |"
        )
        lines.append("| ---: | --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |")
        for rank, signal in enumerate(report.theme_lifecycle.signals[:12], start=1):
            lines.append(_theme_lifecycle_row(rank, signal))
    else:
        lines.append("- 当前没有达到资金试探以上级别的主线生命周期信号。")
    lines.append("")
    for note in report.theme_lifecycle.notes:
        lines.append(f"- {note}")
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
        lines.append(
            f"环境结论：**{best_pulse.name}** 当前最强，状态为 **{best_pulse.status}**，证据包括：{'; '.join(best_pulse.evidence)}。"
        )
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
            lines.append("| 排名 | 主线 | 状态 | 生命周期 | 独立状态 | 顺势候选 |")
            lines.append("| ---: | --- | --- | --- | --- | --- |")
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
    elif report.next_buy.by_theme:
        lines.append("## 顺势候选等待区")
        lines.append("")
        lines.append(f"当前交易闸门为 **{report.trading_gate.state}**，不生成下一笔买入候选；以下仅保留等待确认名单。")
        lines.append("")
        lines.append("| 排名 | 主线 | 状态 | 生命周期 | 独立状态 | 顺势候选 |")
        lines.append("| ---: | --- | --- | --- | --- | --- |")
        for rank, group in enumerate(report.next_buy.by_theme[:6], start=1):
            lines.append(_theme_buy_group_row(rank, group))
        lines.append("")

    lines.append("## 主线黄金坑雷达")
    lines.append("")
    lines.append("黄金坑只扫描前三主线核心股；先识别坑位，再等待止跌确认。市场闸门关闭时一律不把候选写成买点。")
    lines.append("")
    if report.golden_pits.candidates:
        lines.append(
            "| 排名 | 标的 | 主线 | 阶段 | 评分 | 距20日高点 | 单日 | 相对大盘 | 当日/前5日成交 | 基本面 | 当前动作 | 确认条件 | 失效条件 |"
        )
        lines.append("| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |")
        for rank, item in enumerate(report.golden_pits.candidates, start=1):
            lines.append(_golden_pit_row(rank, item))
        lines.append("")
        for item in report.golden_pits.candidates[:5]:
            lines.append(f"- **{item.name} `{item.symbol}`**：{'；'.join(item.reasons)}。")
    else:
        lines.append("- 当前没有达到约束的黄金坑候选，宁可空缺也不把下跌中继包装成机会。")
    lines.append("")
    for note in report.golden_pits.notes:
        lines.append(f"- {note}")
    lines.append("")

    lines.append("## 月线长期箱体观察")
    lines.append("")
    lines.append("寻找18-30个月反复验证上下沿、趋势趋平且成交沉淀的平台；它是等待确认的观察池，不等于立即建仓。")
    lines.append("")
    if report.monthly_bases.candidates:
        lines.append(
            "| 排名 | 标的 | 主题 | 阶段 | 评分 | 箱体月数 | 箱体区间 | 箱体宽度 | 当前位置 | 成交沉淀 | 前高倍数 | 当前动作 | 确认条件 | 失效条件 |"
        )
        lines.append("| ---: | --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- |")
        for rank, item in enumerate(report.monthly_bases.candidates, start=1):
            lines.append(_monthly_base_row(rank, item))
        lines.append("")
        for item in report.monthly_bases.candidates[:5]:
            lines.append(f"- **{item.name} `{item.symbol}`**：{'；'.join(item.reasons)}。")
    else:
        lines.append("- 当前没有通过月线箱体质量和历史主升排除条件的标的。")
    lines.append("")
    for note in report.monthly_bases.notes:
        lines.append(f"- {note}")
    lines.append("")

    if report.expectation_gaps.signals:
        lines.append("## 业绩预期差与价格反应")
        lines.append("")
        lines.append("好业绩是否已经提前交易，要看公告后价格和成交反馈；放量下跌会进入利好兑现风险。")
        lines.append("")
        lines.append("| 标的 | 公告日 | 状态 | 公告后3日 | 成交放大 | 基本面 |")
        lines.append("| --- | --- | --- | ---: | ---: | --- |")
        for item in report.expectation_gaps.signals[:12]:
            lines.append(
                f"| {item.name} `{item.symbol}` | {item.announce_date} | {item.status} | "
                f"{pct(item.reaction_3d)} | {_ratio(item.amount_ratio)} | {item.fundamental_status} |"
            )
        lines.append("")
        for note in report.expectation_gaps.notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append("## 基本面兑现与估值参考")
    lines.append("")
    lines.append(
        f"候选池请求 {report.fundamentals.requested_symbols} 只，核心财务指标覆盖 "
        f"{report.fundamentals.covered_symbols} 只；该评分已经参与顺势组和低位介入组重排。"
    )
    lines.append("")
    if report.fundamentals.snapshots:
        lines.append(
            "| 排名 | 标的 | 报告期 | 状态 | 财务分 | 营收同比 | 净利同比 | ROE | 每股经营现金流 | PB参考 | 营收增速变化 | 利润增速变化 |"
        )
        lines.append("| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for rank, item in enumerate(report.fundamentals.snapshots[:20], start=1):
            lines.append(_fundamental_row(rank, item))
    else:
        lines.append("- 本次未取得候选池核心财务指标，技术与政策候选照常生成，但可信度按未覆盖处理。")
    lines.append("")
    for note in report.fundamentals.notes:
        lines.append(f"- {note}")
    lines.append("")

    if report.target_prices.estimates:
        lines.append("## 目标价与赔率")
        lines.append("")
        lines.append("这里给的是系统交易目标区间；除非研报文本明确写出目标价，否则不冒充券商盈利预测估值目标。")
        lines.append("")
        lines.append(
            "| 排名 | 类型 | 标的 | 主线 | 依据 | 周期 | 当前价 | 系统目标区间 | 上行空间 | 失效价 | 到失效价 | R/R | 信心 | 研报目标参考 |"
        )
        lines.append("| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |")
        for rank, item in enumerate(report.target_prices.estimates[:16], start=1):
            lines.append(_target_price_row(rank, item))
        lines.append("")
        for item in report.target_prices.estimates[:5]:
            if item.evidence:
                lines.append(f"- **{item.name} `{item.symbol}`**：{'；'.join(item.evidence)}。")
        lines.append("")
        for note in report.target_prices.notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append("## 低位资金介入候选")
    lines.append("")
    lines.append(
        "这张表不是顺势追强榜；它寻找仍处在60日中低位、成交额均线开始抬升、短线跌势收敛的股票，适合作为观察/试错池。"
    )
    lines.append("")
    if report.accumulation.candidates:
        lines.append(
            "| 排名 | 主题 | 标的 | 状态 | 评分 | 60日位置 | 距60日高点 | 5日 | 20日 | 成交5/20 | 成交10/30 | 距20日线 | 基本面 | 财务分 | 触发/参与条件 | 失效条件 |"
        )
        lines.append(
            "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |"
        )
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
        lines.append(
            "| 排名 | 主线 | 标的 | 当前状态 | 综合分 | 5日 | 20日 | 成交热度 | 基本面 | 财务分 | 信号数 | 胜率 | 平均收益 | 最差收益 | 平均最大回撤 |"
        )
        lines.append(
            "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"
        )
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
