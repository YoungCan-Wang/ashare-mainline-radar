from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import NextBuyPlan, RadarReport, StrongStockCandidate, TargetPriceEstimate, ThemeLifecycleSignal, pct


@dataclass
class FeishuStatus:
    status: str
    code: int | None = None
    message: str | None = None
    response: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _theme_rank(report: RadarReport) -> dict[str, int]:
    return {theme.name: rank for rank, theme in enumerate(report.themes, start=1)}


def _ordered_lifecycle_signals(report: RadarReport) -> list[ThemeLifecycleSignal]:
    ranks = _theme_rank(report)
    return sorted(
        report.theme_lifecycle.signals,
        key=lambda signal: (ranks.get(signal.theme, len(ranks) + 1), -signal.score),
    )


def build_feishu_text(report: RadarReport) -> str:
    lines = [
        "A股市场主线雷达",
        f"行情日期：{report.data_as_of or 'n/a'}",
        f"扫描模式：{report.mode}，有效标的：{report.scanned_symbols}",
    ]
    if report.themes:
        lines.append("")
        lines.append("主线 TOP3：")
        for idx, theme in enumerate(report.themes[:3], start=1):
            lines.append(
                f"{idx}. {theme.name}｜{theme.status}｜强度 {theme.score:.1f}｜20日广度 {pct(theme.breadth_20d)}"
                f"｜政策 {theme.policy_catalyst_count} 条"
            )
    if report.theme_lifecycle.signals:
        lines.append("")
        lines.append("主线生命周期变化（按当前主线排名）：")
        ranks = _theme_rank(report)
        for signal in _ordered_lifecycle_signals(report)[:4]:
            rank_text = f"第{ranks[signal.theme]}主线" if signal.theme in ranks else "主线榜外"
            lines.append(
                f"- {rank_text}｜{signal.theme}｜{signal.stage}｜本轮启动 {signal.started_at or '待确认'}｜"
                f"主线确认 {signal.confirmed_at or '待确认'}｜阶段始于 {signal.stage_since}｜"
                f"{signal.independence_status} {signal.independent_score:.1f}"
            )
            lines.append(f"  动作：{signal.action}")
    if report.cross_market.themes:
        lines.append("")
        lines.append("A/H联动确认：")
        for signal in report.cross_market.themes[:3]:
            rank = f"A股第{signal.a_share_rank}主线" if signal.a_share_rank else "A股榜外"
            lines.append(
                f"- {signal.theme}｜{signal.status}｜{rank}｜港股5日广度 {pct(signal.hk_breadth_5d)}｜"
                f"港股5日 {pct(signal.hk_avg_ret_5d)}"
            )
    watch = report.price_limit_watch
    if watch.limit_up_touches or watch.limit_down_touches:
        lines.append("")
        lines.append("涨跌停交易结论：")
        lines.append(f"- 天板：{watch.ceiling_verdict}｜{watch.ceiling_reason}")
        lines.append(f"- 地板：{watch.floor_verdict}｜{watch.floor_reason}")
        lines.append(
            f"涨停触及 {watch.limit_up_touches}｜封板 {watch.closed_limit_up}｜首板 {watch.first_board_closed}｜"
            f"一字 {watch.one_price_limit_up}｜炸板 {watch.broken_boards}｜天地板 {watch.ceiling_to_floor}"
        )
        lines.append(
            f"跌停触及 {watch.limit_down_touches}｜封跌停 {watch.closed_limit_down}｜"
            f"一字 {watch.one_price_limit_down}｜"
            f"跌停打开 {watch.broken_floors}｜地天板 {watch.floor_to_ceiling}"
        )
        for signal in watch.signals[:5]:
            lines.append(
                f"- {signal.signal_type}｜{signal.name} {signal.symbol}｜{signal.verdict}｜{signal.action}"
            )
    if report.policy_signals and report.policy_signals.signals:
        lines.append("")
        lines.append("政策催化 TOP3：")
        for idx, signal in enumerate(report.policy_signals.signals[:3], start=1):
            title = signal.evidence[0].title if signal.evidence else "n/a"
            lines.append(f"{idx}. {signal.theme}｜政策分 {signal.score:.1f}｜{title}")
    if report.market_pulses:
        pulse = report.market_pulses[0]
        lines.append("")
        lines.append(f"环境：{pulse.name}｜{pulse.status}｜强度 {pulse.score:.1f}")
    lines.append(
        f"交易闸门：{report.trading_gate.state}｜指数结构 {report.market_structure.status}｜"
        f"{'; '.join(report.trading_gate.reasons)}"
    )
    if report.fundamentals and report.fundamentals.snapshots:
        lines.append("")
        lines.append("基本面兑现 TOP3：")
        for idx, item in enumerate(report.fundamentals.snapshots[:3], start=1):
            lines.append(
                f"{idx}. {item.symbol}｜{item.status}｜财务分 {item.score:.1f}｜营收同比 {item.revenue_yoy or 0:.1f}%｜净利同比 {item.net_income_yoy or 0:.1f}%"
            )
    if report.next_buy and report.next_buy.primary:
        plan = report.next_buy.primary
        lines.append("")
        lines.append("下一笔优先候选：")
        lines.append(f"{plan.name} {plan.symbol}｜{plan.theme}｜{plan.decision}｜优先级 {plan.priority_score:.1f}")
        lines.append(f"参与条件：{plan.entry_plan}")
        lines.append(f"失效条件：{plan.invalidation}")
        if report.next_buy.by_theme:
            lines.append("分主线顺势候选：")
            for group in report.next_buy.by_theme[:4]:
                names = "；".join(f"{item.name} {item.symbol}" for item in group.plans[:2]) or group.note or "暂无候选"
                lines.append(
                    f"- {group.theme}｜{group.theme_status}｜{group.lifecycle_stage}｜"
                    f"{group.independence_status}｜{names}"
                )
    if report.unmapped_pullback.candidates:
        lines.append("")
        lines.append("未映射相对强度回踩（研究准备）：")
        for item in (report.unmapped_pullback.buyable_now or report.unmapped_pullback.candidates)[:3]:
            status = "可买" if item.buyable_now else "观察"
            lines.append(
                f"- {item.name} {item.symbol}｜{status}｜{item.style_tag}｜{item.decision}｜"
                f"优先级 {item.priority_score:.1f}"
            )
    target_estimates = report.target_prices.estimates if report.target_prices else []
    if target_estimates:
        lines.append("")
        lines.append("目标价与赔率：")
        for idx, item in enumerate(target_estimates[:3], start=1):
            valuation_note = _target_valuation_note(item)
            lines.append(
                f"{idx}. {item.name} {item.symbol}｜{item.candidate_type}｜目标 {item.target_low:.2f}-{item.target_high:.2f}｜"
                f"上行 {pct(item.upside_low)}-{pct(item.upside_high)}｜信心 {item.confidence}"
                f"{f'｜{valuation_note}' if valuation_note else ''}"
            )
    accumulation_candidates = report.accumulation.candidates if report.accumulation else []
    if accumulation_candidates:
        lines.append("")
        lines.append("低位资金介入候选：")
        for idx, item in enumerate(accumulation_candidates[:5], start=1):
            amount_ratio = "n/a" if item.amount_ratio_5_20 is None else f"{item.amount_ratio_5_20:.2f}x"
            lines.append(
                f"{idx}. {item.name} {item.symbol}｜{item.primary_theme}｜{item.status}｜评分 {item.score:.1f}｜"
                f"60日位置 {pct(item.range_position_60d)}｜成交5/20 {amount_ratio}"
            )
    if report.golden_pits.candidates:
        lines.append("")
        lines.append("主线黄金坑：")
        for idx, item in enumerate(report.golden_pits.candidates[:5], start=1):
            lines.append(
                f"{idx}. {item.name} {item.symbol}｜{item.theme}｜{item.stage}｜{item.action}｜评分 {item.score:.1f}"
            )
    if report.monthly_bases.candidates:
        lines.append("")
        lines.append("月线长期箱体（等待确认）：")
        for idx, item in enumerate(report.monthly_bases.candidates[:5], start=1):
            themes = "、".join(item.themes) if item.themes else "未映射"
            lines.append(
                f"{idx}. {item.name} {item.symbol}｜{themes}｜{item.stage}｜评分 {item.score:.1f}｜"
                f"箱体 {item.box_low:.2f}-{item.box_high:.2f}｜{item.action}"
            )
    candidates = report.strong_stocks.candidates if report.strong_stocks else []
    if candidates:
        lines.append("")
        lines.append(f"强势个股候选（持有{report.strong_stocks.hold_days}日回测）：")
        for idx, item in enumerate(candidates[:6], start=1):
            bt = item.backtest
            win = "n/a" if not bt or bt.win_rate is None else f"{bt.win_rate * 100:.1f}%"
            avg = "n/a" if not bt or bt.avg_return is None else f"{bt.avg_return * 100:.2f}%"
            signals = 0 if not bt else bt.signals
            lines.append(
                f"{idx}. {item.name} {item.symbol}｜{item.theme}｜{item.status}｜评分 {item.score:.1f}｜"
                f"信号 {signals} 次｜胜率 {win}｜均值 {avg}"
            )
    lines.append("")
    lines.append("提示：仅用于研究和交易准备，不构成投资建议。")
    return "\n".join(lines)


def _dedupe_plans(report: RadarReport) -> list[NextBuyPlan]:
    plans: list[NextBuyPlan] = []
    if report.next_buy.primary:
        plans.append(report.next_buy.primary)
    plans.extend(report.next_buy.alternatives)
    for group in report.next_buy.by_theme:
        plans.extend(group.plans)
    return list({plan.symbol: plan for plan in plans}.values())


_ATTEMPT_DECISIONS = {
    "优先候选，等待回踩",
    "突破确认候选",
    "优先候选，分批确认",
    "主升加速，等待回踩",
}


def _is_fund_name(name: str) -> bool:
    return "ETF" in name.upper() or "基金" in name


def _attempt_cut_reason(candidate: StrongStockCandidate | None, plan: NextBuyPlan) -> str | None:
    """Return the first display-only 建仓 cut that failed, or None if ready."""
    name = plan.name
    if candidate is None:
        return f"{name} 缺少强势回测"
    if plan.decision not in _ATTEMPT_DECISIONS:
        return f"{name} 决策未达建仓"
    if candidate.fundamental_status == "基本面拖累":
        return f"{name} 基本面拖累"
    if candidate.expectation_status == "利好兑现风险":
        return f"{name} 利好兑现风险"
    if candidate.fundamental_status == "未覆盖" and not _is_fund_name(candidate.name):
        return f"{name} 基本面未覆盖"
    if plan.priority_score < 70:
        return f"{name} 优先级 {plan.priority_score:.0f}<70"
    backtest = candidate.backtest
    if not backtest:
        return f"{name} 无15日回测"
    if backtest.signals < 5:
        return f"{name} 样本 {backtest.signals}<5"
    if backtest.win_rate is None:
        return f"{name} 胜率缺失"
    if backtest.win_rate < 0.55:
        return f"{name} 胜率 {backtest.win_rate * 100:.0f}%<55%"
    if backtest.avg_return is None:
        return f"{name} 均值缺失"
    if backtest.avg_return <= 0:
        return f"{name} 均值 {backtest.avg_return * 100:.1f}%≤0"
    if candidate.ret_5d is not None and candidate.ret_5d >= 0.15:
        return f"{name} 5日涨幅 {candidate.ret_5d * 100:.0f}%≥15%"
    return None


def _attempt_ready(candidate: StrongStockCandidate | None, plan: NextBuyPlan) -> bool:
    return _attempt_cut_reason(candidate, plan) is None


def _empty_attempt_copy(
    report: RadarReport,
    candidates: dict[str, StrongStockCandidate],
) -> str:
    if report.trading_gate.level == "red":
        return "**市场风险闸门已关闭，今日暂停新增仓位。**"
    primary = report.next_buy.primary
    if primary is None:
        return "**今日没有同时通过15日回测、基本面和位置约束的新开仓标的。**"
    considered = [primary, *report.next_buy.alternatives]
    reasons: list[str] = []
    seen: set[str] = set()
    for plan in considered:
        if plan.symbol in seen:
            continue
        seen.add(plan.symbol)
        reason = _attempt_cut_reason(candidates.get(plan.symbol), plan)
        if reason:
            reasons.append(reason)
    if not reasons:
        return "**今日没有同时通过15日回测、基本面和位置约束的新开仓标的。**"
    return f"**优先候选未过建仓裁切：** {'；'.join(reasons)}。"


def _hold_ready(candidate: StrongStockCandidate, theme_phase: str | None) -> bool:
    backtest = candidate.backtest
    is_fund = "ETF" in candidate.name.upper() or "基金" in candidate.name
    crowded_without_support = bool(
        theme_phase and theme_phase.startswith("山顶高拥挤") and theme_phase != "山顶高拥挤·业绩支撑"
    )
    return bool(
        candidate.status in {"主升确认", "趋势延续"}
        and candidate.fundamental_status != "基本面拖累"
        and (candidate.fundamental_status != "未覆盖" or is_fund)
        and candidate.expectation_status != "利好兑现风险"
        and not crowded_without_support
        and backtest
        and backtest.signals >= 3
        and backtest.win_rate is not None
        and backtest.win_rate >= 0.5
        and backtest.avg_return is not None
        and backtest.avg_return > 0
    )


def _waiting_note(
    plan: NextBuyPlan,
    gate_level: str,
    candidate: StrongStockCandidate | None = None,
) -> str:
    if gate_level == "red":
        return "交易闸门关闭：仅观察；待指数结构脱离破位确认后，再重新评估原触发条件。"
    if (
        candidate
        and candidate.fundamental_status == "未覆盖"
        and not ("ETF" in candidate.name.upper() or "基金" in candidate.name)
    ):
        return f"{plan.entry_plan}\n基本面未覆盖：保留在等待区，补齐已公告财务数据前不进入尝试建仓。"
    return plan.entry_plan


def _target_text(target: TargetPriceEstimate | None) -> str:
    if target is None:
        return "目标区待确认"
    valuation_note = _target_valuation_note(target)
    text = f"目标 {target.target_low:.2f}-{target.target_high:.2f}｜赔率 {target.reward_risk_low or 0:.1f}-{target.reward_risk_high or 0:.1f}"
    return f"{text}\n{valuation_note}" if valuation_note else text


def _target_valuation_note(target: TargetPriceEstimate) -> str | None:
    prefix = "估值风格代理："
    for evidence in target.evidence:
        if evidence.startswith(prefix):
            return evidence.replace(prefix, "估值：", 1).replace("，目标上沿约束 ", "｜上沿约", 1)
    return None


def _trade_block(
    plan: NextBuyPlan,
    candidate: StrongStockCandidate | None,
    target: TargetPriceEstimate | None,
    include_entry: bool,
) -> str:
    backtest = candidate.backtest if candidate else None
    win = "n/a" if not backtest or backtest.win_rate is None else f"{backtest.win_rate * 100:.0f}%"
    avg = "n/a" if not backtest or backtest.avg_return is None else f"{backtest.avg_return * 100:.1f}%"
    is_fund = bool(candidate and ("ETF" in candidate.name.upper() or "基金" in candidate.name))
    fundamental = "ETF分散载体" if is_fund else candidate.fundamental_status if candidate else "基本面未覆盖"
    lines = [
        f"**{plan.name} `{plan.symbol}`**｜{plan.theme}｜{plan.lifecycle_stage}｜优先级 {plan.priority_score:.1f}",
        f"{report_hold_days(candidate)}日回测：胜率 {win}｜均值 {avg}｜{fundamental}",
        _target_text(target),
    ]
    if candidate and candidate.expectation_status != "未覆盖":
        lines.append(f"业绩价格反馈：{candidate.expectation_status}")
    if include_entry:
        lines.append(f"**触发：** {plan.entry_plan}")
    lines.append(f"**退出：** {plan.invalidation}")
    return "\n".join(lines)


def report_hold_days(candidate: StrongStockCandidate | None) -> int:
    return candidate.backtest.hold_days if candidate and candidate.backtest else 15


def _div(content: str) -> dict[str, Any]:
    return {"tag": "markdown", "content": content}


def _fmt_price(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _gate_section(report: RadarReport) -> dict[str, Any]:
    gate = report.trading_gate
    structure = report.market_structure
    gate_color = "red" if gate.level == "red" else "orange" if gate.level == "orange" else "green"
    lines = [
        f"<font color='{gate_color}'>**今日交易状态：{gate.state}**</font>",
        f"指数结构：**{structure.status}**｜确认分 {structure.score:.0f}｜闸门分 {gate.score:.0f}",
    ]
    if gate.level == "red":
        lines.append("<font color='red'>**关闭原因**</font>")
        for reason in gate.reasons[:6] or ["环境数据不足"]:
            lines.append(f"· {reason}")
        if structure.evidence:
            lines.append("**结构证据**")
            for item in structure.evidence[:6]:
                lines.append(f"· {item}")
        lines.append("解锁条件：三大指数多数收复20日线、脱离「破位确认」后，才会重新评估试错/开仓。")
    else:
        reason_text = "；".join(gate.reasons) or "环境数据不足"
        lines.append(f"依据：{reason_text}")
    lines.append(f"允许：{'；'.join(gate.allowed_actions)}")
    return _div("\n".join(lines))


def _normalize_dashboard_url(dashboard_url: str | None) -> str | None:
    if not dashboard_url:
        return None
    url = dashboard_url.strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"dashboard_url must be an http(s) URL, got: {dashboard_url!r}")
    return url


def _dashboard_button(url: str) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "打开完整作战台"},
        "type": "primary",
        "width": "fill",
        "behaviors": [
            {
                "type": "open_url",
                "default_url": url,
                "pc_url": url,
                "ios_url": url,
                "android_url": url,
            }
        ],
    }


def build_feishu_card(report: RadarReport, dashboard_url: str | None = None) -> dict[str, Any]:
    candidates = {item.symbol: item for item in report.strong_stocks.candidates}
    targets = {item.symbol: item for item in report.target_prices.estimates}
    phase_by_theme = {item.name: item.price_phase for item in report.themes}
    plans = _dedupe_plans(report)
    hold = [
        plan
        for plan in plans
        if (candidate := candidates.get(plan.symbol)) and _hold_ready(candidate, phase_by_theme.get(candidate.theme))
    ][:3]
    attempt = [plan for plan in plans if _attempt_ready(candidates.get(plan.symbol), plan)][:2]
    if report.trading_gate.level == "red":
        attempt = []
    occupied = {item.symbol for item in [*attempt, *hold]}
    waiting = [plan for plan in plans if plan.symbol not in occupied][:3]

    lifecycle_by_theme = {signal.theme: signal for signal in report.theme_lifecycle.signals}
    theme_ranking = ["<font color='blue'>**当前主线排名**</font>"]
    for rank, theme in enumerate(report.themes[:4], start=1):
        lifecycle = lifecycle_by_theme.get(theme.name)
        stage = lifecycle.stage if lifecycle else "生命周期待确认"
        theme_ranking.append(
            f"**{rank}. {theme.name}**｜强度 {theme.score:.0f}｜{theme.status}｜{stage}｜{theme.price_phase}"
        )
    if len(theme_ranking) == 1:
        theme_ranking.append("暂无确认主线")
    theme_ranking_text = "\n".join(theme_ranking)
    market = report.market_pulses[0] if report.market_pulses else None
    market_text = f"{market.name}｜{market.status}｜{market.score:.0f}" if market else "环境未确认"
    hold_days = report.strong_stocks.hold_days
    elements: list[dict[str, Any]] = [
        _div(
            f"**行情 {report.data_as_of or 'n/a'}**　扫描 {report.scanned_symbols} 只\n"
            f"{theme_ranking_text}\n环境：{market_text}　策略周期：**{hold_days}个交易日**"
        ),
    ]
    ranks = _theme_rank(report)
    lifecycle_signals = _ordered_lifecycle_signals(report)[:4]
    if lifecycle_signals:
        lifecycle_lines = ["<font color='blue'>**主线生命周期变化**</font>（按当前主线排名）"]
        for signal in lifecycle_signals:
            transition = "｜**新变化**" if signal.is_new_transition else ""
            rank_text = f"第{ranks[signal.theme]}主线" if signal.theme in ranks else "主线榜外"
            independence = (
                f"｜<font color='orange'>**{signal.independence_status} {signal.independent_score:.0f}**</font>"
                if signal.independence_status == "逆势独立主线"
                else ""
            )
            lifecycle_lines.append(
                f"**{rank_text}｜{signal.theme}｜{signal.stage}**{transition}{independence}\n"
                f"启动 {signal.started_at or '待确认'}｜确认 {signal.confirmed_at or '待确认'}｜"
                f"阶段始于 {signal.stage_since}\n"
                f"5日广度 {pct(signal.breadth_5d)}｜20日广度 {pct(signal.breadth_20d)}｜"
                f"成交 {signal.amount_heat or 0:.2f}x｜相对全市场5日 {pct(signal.relative_strength_5d)}\n"
                f"动作：{signal.action}"
            )
        if report.trading_gate.level == "red":
            lifecycle_lines.append("<font color='red'>交易闸门关闭：保留主线预警，但今日不据此新增仓位。</font>")
        elements.extend([{"tag": "hr"}, _div("\n\n".join(lifecycle_lines))])
    if report.cross_market.themes:
        cross_lines = ["<font color='blue'>**A/H联动确认**</font>（观察信号，暂不直接加分）"]
        for signal in report.cross_market.themes[:3]:
            rank = f"A股第{signal.a_share_rank}主线" if signal.a_share_rank else "A股榜外"
            leaders = "、".join(f"{item.name} `{item.symbol}`" for item in signal.leaders[:3]) or "暂无"
            cross_lines.append(
                f"**{signal.theme}｜{signal.status}**｜{rank}｜联动分 {signal.score:.0f}\n"
                f"港股5日广度 {pct(signal.hk_breadth_5d)}｜20日广度 {pct(signal.hk_breadth_20d)}｜"
                f"5日 {pct(signal.hk_avg_ret_5d)}｜成交量热度 "
                f"{f'{signal.hk_amount_heat:.2f}x' if signal.hk_amount_heat is not None else 'n/a'}\n"
                f"港股通核心：{leaders}\n动作：{signal.action}"
            )
        if report.cross_market.ah_pairs:
            pair_text = "；".join(
                f"{pair.company} {pair.leader}({pct(pair.spread_5d)})" for pair in report.cross_market.ah_pairs[:4]
            )
            cross_lines.append(f"A/H同公司动量：{pair_text}")
        elements.extend([{"tag": "hr"}, _div("\n\n".join(cross_lines))])
    watch = report.price_limit_watch
    if watch.limit_up_touches or watch.limit_down_touches:
        chase_case = next(
            (case for case in watch.backtest_cases if case.name == "首板确认后次日开盘追"),
            None,
        )
        floor_case = next(
            (case for case in watch.backtest_cases if case.name == "跌停打开后次日开盘抄"),
            None,
        )
        watch_lines = [
            "<font color='red'>**涨跌停交易结论**</font>",
            f"**天板：{watch.ceiling_verdict}**｜{watch.ceiling_reason}",
            f"**地板：{watch.floor_verdict}**｜{watch.floor_reason}",
        ]
        if chase_case:
            watch_lines.append(
                f"追首板样本外 `{chase_case.test_trades}` 笔｜3日胜率 `{pct(chase_case.win_rate_3d)}`｜"
                f"5日均值 `{pct(chase_case.avg_return_5d)}`｜5%尾部 `{pct(chase_case.p05_return_5d)}`"
            )
        if floor_case:
            watch_lines.append(
                f"抄跌停打开样本外 `{floor_case.test_trades}` 笔｜3日胜率 `{pct(floor_case.win_rate_3d)}`｜"
                f"5日均值 `{pct(floor_case.avg_return_5d)}`｜5%尾部 `{pct(floor_case.p05_return_5d)}`"
            )
        if watch.reopen_conditions:
            watch_lines.append(f"**重开门槛**｜{watch.reopen_conditions[-1]}")
        watch_lines.extend([
            f"证据截至 `{watch.evidence_as_of}`｜收盘确认后、次日开盘可成交才计入",
            f"涨停触及 {watch.limit_up_touches}｜封板 {watch.closed_limit_up}｜首板 {watch.first_board_closed}｜"
            f"一字 {watch.one_price_limit_up}｜炸板 {watch.broken_boards}｜天地板 {watch.ceiling_to_floor}",
            f"跌停触及 {watch.limit_down_touches}｜封跌停 {watch.closed_limit_down}｜"
            f"一字 {watch.one_price_limit_down}｜"
            f"跌停打开 {watch.broken_floors}｜地天板 {watch.floor_to_ceiling}",
        ])
        for signal in watch.signals[:6]:
            themes = "、".join(signal.themes) if signal.themes else "未映射"
            watch_lines.append(
                f"**{signal.signal_type}｜{signal.name} `{signal.symbol}`｜{signal.verdict}**｜{themes}\n{signal.action}"
            )
        elements.extend([{"tag": "hr"}, _div("\n\n".join(watch_lines))])
    elements.extend(
        [
            {"tag": "hr"},
            _gate_section(report),
            {"tag": "hr"},
            _div("<font color='red'>**一、可尝试建仓（触发后）**</font>\n只在触发条件出现后分批，不等于开盘直接买。"),
        ]
    )
    if attempt:
        for plan in attempt:
            elements.append(_div(_trade_block(plan, candidates.get(plan.symbol), targets.get(plan.symbol), True)))
    else:
        elements.append(_div(_empty_attempt_copy(report, candidates)))

    hold_title = "已有仓位：仅留强去弱" if report.trading_gate.level == "red" else "已有仓位可继续持有"
    elements.extend(
        [
            {"tag": "hr"},
            _div(f"<font color='green'>**二、{hold_title}**</font>\n仅适用于已经持有；主线和退出条件失效时不再拿。"),
        ]
    )
    if hold:
        for plan in hold:
            elements.append(_div(_trade_block(plan, candidates.get(plan.symbol), targets.get(plan.symbol), False)))
    else:
        elements.append(_div("当前没有达到继续持有标准的顺势候选。"))

    elements.extend([{"tag": "hr"}, _div("<font color='orange'>**三、等待回踩或确认**</font>")])
    if waiting:
        for plan in waiting:
            elements.append(
                _div(
                    f"**{plan.name} `{plan.symbol}`**｜{plan.theme}｜{plan.lifecycle_stage}\n"
                    f"{_waiting_note(plan, report.trading_gate.level, candidates.get(plan.symbol))}"
                )
            )
    else:
        elements.append(_div("暂无等待候选。"))

    unmapped = report.unmapped_pullback
    if unmapped.candidates:
        lines = [
            "<font color='grey'>**未映射相对强度回踩**</font>（研究准备，可从日报 JSON/MD 复核；不写入跟踪库）",
            f"扫描 {unmapped.scanned} 只｜可买 {len(unmapped.buyable_now)}｜观察 {max(0, len(unmapped.candidates) - len(unmapped.buyable_now))}",
        ]
        for item in (unmapped.buyable_now or unmapped.candidates)[:3]:
            zone = (
                f"{item.entry_zone_low:.2f}-{item.entry_zone_high:.2f}"
                if item.entry_zone_low is not None and item.entry_zone_high is not None
                else "n/a"
            )
            status = "可买" if item.buyable_now else "观察"
            lines.append(
                f"**{item.name} `{item.symbol}`**｜{status}｜{item.style_tag}｜优先级 {item.priority_score:.0f}\n"
                f"{item.decision}｜买入区 {zone}｜确认 {_fmt_price(item.confirm_price)}｜止损 {_fmt_price(item.stop_price)}\n"
                f"{item.gate_action}"
            )
        elements.extend([{"tag": "hr"}, _div("\n\n".join(lines))])

    golden_pits = report.golden_pits.candidates[:3]
    if golden_pits:
        lines = ["<font color='orange'>**四、主线黄金坑（先等确认）**</font>"]
        for item in golden_pits:
            lines.append(
                f"**{item.name} `{item.symbol}`**｜{item.theme}｜{item.stage}｜评分 {item.score:.1f}\n"
                f"动作：{item.action}\n确认：{item.confirmation}\n失效：{item.invalidation}"
            )
        elements.extend([{"tag": "hr"}, _div("\n\n".join(lines))])

    monthly_bases = report.monthly_bases.candidates[:3]
    if monthly_bases:
        lines = ["<font color='blue'>**五、月线长期箱体（等待确认）**</font>"]
        for item in monthly_bases:
            themes = "、".join(item.themes) if item.themes else "未映射"
            lines.append(
                f"**{item.name} `{item.symbol}`**｜{themes}｜{item.stage}｜评分 {item.score:.1f}\n"
                f"箱体：{item.box_low:.2f}-{item.box_high:.2f}（{item.box_months}个月）｜当前位置 {item.box_position * 100:.0f}%\n"
                f"动作：{item.action}\n确认：{item.confirmation}\n失效：{item.invalidation}"
            )
        elements.extend([{"tag": "hr"}, _div("\n\n".join(lines))])

    low_position = report.accumulation.candidates[:3]
    if low_position:
        lines = ["<font color='grey'>**六、低位资金观察（不是立即建仓）**</font>"]
        for item in low_position:
            lines.append(
                f"{item.name} `{item.symbol}`｜{item.primary_theme}｜{item.status}｜"
                f"评分 {item.score:.1f}｜成交5/20 {item.amount_ratio_5_20 or 0:.2f}x"
            )
        elements.extend([{"tag": "hr"}, _div("\n".join(lines))])

    elements.extend(
        [
            {"tag": "hr"},
            _div(
                "**统一纪律**\n"
                "组合基准最多同时两仓、单仓不超过总资金25%；首笔只用计划仓位的1/3。只有已有浮盈且趋势确认后才递减加仓，"
                "亏损中不补仓。持有10-20个交易日不是死拿，跌破失效位、主线连续两日退出前三或基本面降级时提前退出。\n"
                "<font color='grey'>仅用于研究和交易准备，不构成投资建议。</font>"
            ),
        ]
    )
    normalized_url = _normalize_dashboard_url(dashboard_url)
    if normalized_url:
        elements.extend([{"tag": "hr"}, _dashboard_button(normalized_url)])
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "style": {"text_size": {"normal_v2": {"default": "normal", "pc": "normal", "mobile": "normal"}}},
        },
        "header": {
            "template": "red",
            "title": {
                "tag": "plain_text",
                "content": f"A股主线作战卡｜10-20日｜{report.data_as_of or 'n/a'}",
            },
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": elements,
        },
    }


_SHADOW_BLOCK_LABELS = {
    "sealed_limit_up": "涨停买不进",
    "sealed_limit_down": "跌停卖不出",
    "insufficient_cash": "现金不够",
    "t1": "T+1 不能卖",
    "suspension": "停牌",
    "missing_bar": "缺行情不能成交",
}


def _cny(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.2f}"


def _signed_cny(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.2f}"


def _shadow_block_label(event: dict[str, Any]) -> str:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    reason = str(payload.get("reason") or event.get("event_type") or "")
    return _SHADOW_BLOCK_LABELS.get(reason, reason)


def build_shadow_feishu_card(
    snapshot: dict[str, Any],
    *,
    status: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    account = snapshot.get("account") if isinstance(snapshot.get("account"), dict) else {}
    positions = snapshot.get("positions") if isinstance(snapshot.get("positions"), list) else []
    events = snapshot.get("today_events") if isinstance(snapshot.get("today_events"), list) else []
    as_of = snapshot.get("as_of") or account.get("as_of") or "n/a"
    stale = status in {"failed", "skipped"}
    fills = [item for item in events if item.get("event_type") in {"fill_buy", "fill_sell"}]
    blocked = [
        item
        for item in events
        if item.get("event_type") in {"entry_blocked", "exit_delayed", "skip_insufficient_cash", "skip_t1"}
    ]
    lines = [
        f"**净值 {_cny(account.get('equity'))}**　现金 {_cny(account.get('cash'))}　市值 {_cny(account.get('market_value'))}",
        f"累计盈亏 {_signed_cny(account.get('pnl_total'))}　当日 {_signed_cny(account.get('pnl_day'))}　基准 {_cny(account.get('initial_capital') or 100000)}",
    ]
    if stale:
        lines.insert(0, f"<font color='red'>**影子账户未刷新（{status}）**</font>\n{message or '未写入现金账本'}")
    elements: list[dict[str, Any]] = [_div("\n".join(lines))]
    hold_lines = ["<font color='blue'>**持仓**</font>"]
    if positions:
        for item in positions:
            shares = int(item.get("shares") or 0)
            avg_cost = float(item.get("avg_cost") or 0)
            mark = float(item.get("last_mark") or 0)
            unrealized = (mark - avg_cost) * shares if avg_cost and mark else 0
            sellable = int(item.get("sellable_shares") or 0)
            hold_lines.append(
                f"**{item.get('name') or ''} `{item.get('symbol')}`**　{shares}股"
                f"{'（T+1）' if sellable < shares else ''}\n"
                f"成本 {_cny(avg_cost)}　现价 {_cny(mark)}　浮盈亏 {_signed_cny(unrealized)}"
            )
    else:
        hold_lines.append("当前空仓")
    elements.extend([{"tag": "hr"}, _div("\n".join(hold_lines))])

    fill_lines = ["<font color='green'>**今日成交**</font>"]
    if fills:
        for item in fills:
            side = "买入" if item.get("event_type") == "fill_buy" else "卖出"
            fees = item.get("fees") if isinstance(item.get("fees"), dict) else {}
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            fill_lines.append(
                f"{side} `{item.get('symbol')}`　{item.get('qty') or 0}股 @ {_cny(item.get('price'))}"
                f"　费用 {_cny(fees.get('total'))}"
            )
            reason_note = payload.get("reason_note")
            price_note = payload.get("price_note")
            if reason_note:
                fill_lines.append(f"成交理由：{reason_note}")
            if price_note:
                fill_lines.append(f"价格：{price_note}")
    else:
        fill_lines.append("今日无成交")
    elements.extend([{"tag": "hr"}, _div("\n".join(fill_lines))])

    block_lines = ["<font color='orange'>**今日阻断**</font>"]
    if blocked:
        for item in blocked:
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            block_lines.append(f"`{item.get('symbol')}`　{_shadow_block_label(item)}")
            if payload.get("reason_note"):
                block_lines.append(f"成交理由：{payload['reason_note']}")
            if payload.get("price_note"):
                block_lines.append(f"价格：{payload['price_note']}")
    else:
        block_lines.append("今日无阻断")
    elements.extend(
        [
            {"tag": "hr"},
            _div("\n".join(block_lines)),
            {"tag": "hr"},
            _div("<font color='grey'>影子账户为独立 10 万现金账本，含手续费、手数与 T+1；不是雷达作战卡，也不代表实盘持仓。</font>"),
        ]
    )
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "style": {"text_size": {"normal_v2": {"default": "normal", "pc": "normal", "mobile": "normal"}}},
        },
        "header": {
            "template": "orange" if stale else "blue",
            "title": {
                "tag": "plain_text",
                "content": f"影子账户｜{'未刷新' if stale else '现金账本'}｜{as_of}",
            },
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": elements,
        },
    }


def _post_feishu_payload(webhook_url: str, payload: dict[str, Any], timeout: float) -> FeishuStatus:
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "ashare-mainline-radar/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return FeishuStatus(status="failed", message=f"Feishu webhook request failed: {exc}")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return FeishuStatus(status="failed", message=f"Feishu webhook returned non-JSON response: {body[:160]}")
    status_code = parsed.get("StatusCode")
    code = parsed.get("code")
    if status_code not in (None, 0):
        return FeishuStatus(
            status="failed", code=status_code, message=str(parsed.get("msg") or parsed), response=parsed
        )
    if code not in (None, 0):
        return FeishuStatus(status="failed", code=code, message=str(parsed.get("msg") or parsed), response=parsed)
    return FeishuStatus(status="sent", code=0, message=str(parsed.get("msg") or "ok"), response=parsed)


def post_feishu_card(webhook_url: str, card: dict[str, Any], timeout: float = 15.0) -> FeishuStatus:
    return _post_feishu_payload(webhook_url, {"msg_type": "interactive", "card": card}, timeout)


def post_feishu_text(webhook_url: str, text: str, timeout: float = 15.0) -> FeishuStatus:
    return _post_feishu_payload(webhook_url, {"msg_type": "text", "content": {"text": text}}, timeout)


def write_feishu_status(path: str | Path, status: FeishuStatus) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(status.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
