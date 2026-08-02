from __future__ import annotations

from .execution import TradeExecutionPlan, build_trade_execution_plan
from .models import (
    MarketPulse,
    NextBuyPlan,
    NextBuyReport,
    StrongStockCandidate,
    ThemeBuyGroup,
    ThemeLifecycleReport,
    ThemeLifecycleSignal,
    ThemeSnapshot,
    TradingGate,
)
from .strategy_rules import theme_crowding_blocks_entry


def _fmt_price(value: float) -> str:
    return f"{value:.2f}"


def _theme_status(theme_name: str, themes: list[ThemeSnapshot]) -> str:
    for theme in themes:
        if theme.name == theme_name:
            return theme.status
    return "未知"


def _market_note(market_pulses: list[MarketPulse]) -> str:
    if not market_pulses:
        return "市场环境未确认"
    top = market_pulses[0]
    return f"{top.name}：{top.status}，强度 {top.score:.1f}"


def _is_fund(candidate: StrongStockCandidate) -> bool:
    return "ETF" in candidate.name.upper() or "基金" in candidate.name


def _priority_score(
    candidate: StrongStockCandidate,
    theme_status: str,
    market_pulses: list[MarketPulse],
    theme_phase: str = "阶段未确认",
    lifecycle: ThemeLifecycleSignal | None = None,
) -> float:
    score = candidate.score
    backtest = candidate.backtest
    if theme_status == "主线成立":
        score += 4.0
    elif theme_status == "主线候选":
        score += 1.5
    if backtest and backtest.win_rate is not None:
        score += max(-4.0, min(5.0, (backtest.win_rate - 0.5) * 16.0))
    if backtest and backtest.avg_return is not None:
        score += max(-4.0, min(5.0, backtest.avg_return / 0.05 * 5.0))
    if market_pulses and market_pulses[0].status in {"风险偏好转强", "结构性友好"}:
        score += 2.0
    if candidate.ret_5d is not None and candidate.ret_5d > 0.18:
        score -= 5.0
    if candidate.backtest and candidate.backtest.worst_return is not None and candidate.backtest.worst_return < -0.15:
        score -= 4.0
    if candidate.fundamental_status == "基本面拖累":
        score -= 10.0
    elif candidate.fundamental_status == "未覆盖":
        score -= 2.0
    if theme_phase.startswith("山顶高拥挤"):
        score -= 3.0 if candidate.fundamental_status == "基本面兑现" else 7.0
    elif theme_phase == "山谷待反转":
        score -= 5.0
    if lifecycle:
        if lifecycle.stage == "主线确认":
            score += 2.0
        elif lifecycle.stage == "主线回踩":
            score -= 6.0
        elif lifecycle.stage == "退潮预警":
            score -= 12.0
        if lifecycle.independence_status == "逆势独立主线":
            score += 3.0
    return round(max(0.0, min(100.0, score)), 2)


def _decision(
    candidate: StrongStockCandidate,
    theme_phase: str,
    lifecycle: ThemeLifecycleSignal | None,
) -> str:
    if candidate.expectation_status == "利好兑现风险":
        return "利好兑现风险，等待筹码稳定"
    if candidate.fundamental_status == "基本面拖累":
        return "观察候选，等待基本面修复"
    if (
        candidate.fundamental_status == "未覆盖"
        and not _is_fund(candidate)
        and lifecycle
        and lifecycle.stage == "主升加速"
        and candidate.ret_5d is not None
        and candidate.ret_5d >= 0.15
    ):
        return "主升加速，禁止追高；基本面未覆盖"
    if candidate.fundamental_status == "未覆盖" and not _is_fund(candidate):
        return "基本面未覆盖，等待财务确认"
    if theme_crowding_blocks_entry(theme_phase):
        if theme_phase.endswith("兑现不足"):
            return "高位拥挤且兑现不足，等待降温"
        return "高位拥挤，停止新仓"
    if theme_phase == "山谷待反转":
        return "低位待反转确认"
    if lifecycle:
        if lifecycle.stage == "扩散启动":
            return "扩散启动，等待主线确认"
        if lifecycle.stage == "主线回踩":
            return "主线回踩，等待止跌确认"
        if lifecycle.stage == "退潮预警":
            return "退潮预警，停止新仓"
        if lifecycle.stage == "主升加速":
            if candidate.ret_5d is not None and candidate.ret_5d >= 0.15:
                return "主升加速，禁止追高"
            return "主升加速，等待回踩"
    if candidate.ret_5d is not None and candidate.ret_5d >= 0.15:
        return "优先候选，等待回踩"
    if candidate.status == "突破观察":
        return "突破确认候选"
    return "优先候选，分批确认"


def _entry_plan(
    candidate: StrongStockCandidate,
    lifecycle: ThemeLifecycleSignal | None,
    execution: TradeExecutionPlan,
) -> str:
    if lifecycle and lifecycle.stage == "主线回踩":
        return (
            f"先等止跌；重新站上 {_fmt_price(execution.entry_zone_high)} 且板块广度回升后再评估，"
            "下跌过程中不补仓。"
        )
    if lifecycle and lifecycle.stage == "扩散启动":
        return "只进入观察池；等待20日广度、核心股和ETF同步完成主线确认。"
    if execution.entry_mode == "breakout_close_confirm":
        return (
            f"未来{execution.valid_for_days}个交易日内，收盘站上 {_fmt_price(execution.confirm_price)} 且当日收阳；"
            "下一交易日开盘未封涨停时执行首笔，封死涨停则取消本次计划。"
        )
    return (
        f"未来{execution.valid_for_days}个交易日内，最低价触及 "
        f"{_fmt_price(execution.entry_zone_low)}-{_fmt_price(execution.entry_zone_high)}，"
        f"收盘重新站上 {_fmt_price(execution.entry_zone_high)} 且收阳；"
        "下一交易日开盘未封涨停时执行首笔。"
    )


def _invalidation(candidate: StrongStockCandidate, execution: TradeExecutionPlan) -> str:
    soft_stop = candidate.last_close * 0.95
    return (
        f"跌破 {_fmt_price(soft_stop)} 先降级观察；收盘跌破 {_fmt_price(execution.stop_price)} "
        "或主线连续两日退出前三，下一可成交交易日退出；封死跌停时顺延，不假设能够卖出。"
    )


def _position_note(
    candidate: StrongStockCandidate,
    lifecycle: ThemeLifecycleSignal | None,
    execution: TradeExecutionPlan,
) -> str:
    backtest = candidate.backtest
    hold_days = backtest.hold_days if backtest else 15
    if backtest and backtest.worst_return is not None and backtest.worst_return < -0.12:
        note = (
            f"按{hold_days}个交易日波段处理；历史最差信号回撤较大，首笔不超过计划仓位1/3。"
            "仅在已有浮盈、主线延续且回踩确认后递减加仓，亏损中不补仓。"
        )
    else:
        note = (
            f"按{hold_days}个交易日波段处理；首笔只用计划仓位1/3。"
            "仅在已有浮盈、主线延续且回踩确认后递减加仓，跌破失效位不补仓。"
        )
    note = (
        "组合基准最多同时两仓、单仓不超过总资金"
        f"{execution.max_position_fraction * 100:.0f}%；首笔约占总资金"
        f"{execution.initial_position_fraction * 100:.1f}%。" + note
    )
    if lifecycle and lifecycle.independence_status == "逆势独立主线":
        note += "当前属于弱市独立主线，只按试错仓处理，不因板块强势放宽总仓位。"
    return note


def _evidence(
    candidate: StrongStockCandidate,
    theme_status: str,
    market_pulses: list[MarketPulse],
    lifecycle: ThemeLifecycleSignal | None,
) -> list[str]:
    evidence = [f"{candidate.theme}：{theme_status}", f"个股状态：{candidate.status}，强度 {candidate.score:.1f}"]
    if candidate.ret_5d is not None:
        evidence.append(f"5日涨幅 {candidate.ret_5d * 100:.2f}%")
    if candidate.ret_20d is not None:
        evidence.append(f"20日涨幅 {candidate.ret_20d * 100:.2f}%")
    if candidate.amount_ratio is not None:
        evidence.append(f"成交热度 {candidate.amount_ratio:.2f}x")
    if candidate.fundamental_score is not None:
        evidence.append(f"{candidate.fundamental_status}，财务分 {candidate.fundamental_score:.1f}")
    if candidate.backtest:
        win = "n/a" if candidate.backtest.win_rate is None else f"{candidate.backtest.win_rate * 100:.1f}%"
        avg = "n/a" if candidate.backtest.avg_return is None else f"{candidate.backtest.avg_return * 100:.2f}%"
        evidence.append(f"历史信号 {candidate.backtest.signals} 次，胜率 {win}，均值 {avg}")
    if lifecycle:
        evidence.append(f"主线生命周期：{lifecycle.stage}")
        if lifecycle.independence_status == "逆势独立主线":
            evidence.append(f"逆势独立主线，独立分 {lifecycle.independent_score:.1f}")
    evidence.append(_market_note(market_pulses))
    return evidence


def _risk_notes(candidate: StrongStockCandidate) -> list[str]:
    notes = ["这不是自动下单信号，实盘前仍需确认指数环境、流动性、公告和个人仓位上限。"]
    if candidate.ret_5d is not None and candidate.ret_5d >= 0.15:
        notes.append("短线涨幅较大，追高性价比下降，优先等回踩或盘中换手确认。")
    if candidate.backtest and candidate.backtest.signals < 5:
        notes.append("历史信号样本偏少，回测统计可信度有限。")
    if candidate.backtest and candidate.backtest.avg_return is not None and candidate.backtest.avg_return <= 0:
        notes.append("历史信号平均收益不佳，只能作为观察，不应作为优先买入。")
    if candidate.fundamental_status == "基本面拖累":
        notes.append("最新已公告财务指标形成拖累，不进入主动追涨序列，等待增长或现金流修复。")
    elif candidate.fundamental_status == "未覆盖":
        notes.append("核心财务指标未覆盖，候选可信度降级，实盘前需人工核对最新财报。")
    if candidate.expectation_status == "利好兑现风险":
        notes.append("业绩公告后出现放量负反馈，可能是预期已提前交易；等待筹码稳定后再重新评估。")
    return notes


def _build_plan(
    candidate: StrongStockCandidate,
    themes: list[ThemeSnapshot],
    market_pulses: list[MarketPulse],
    lifecycle: ThemeLifecycleSignal | None,
) -> NextBuyPlan:
    theme = next((item for item in themes if item.name == candidate.theme), None)
    status = theme.status if theme else _theme_status(candidate.theme, themes)
    phase = theme.price_phase if theme else "阶段未确认"
    hold_days = candidate.backtest.hold_days if candidate.backtest else 15
    execution = build_trade_execution_plan(candidate.last_close, candidate.status, hold_days=hold_days)
    return NextBuyPlan(
        symbol=candidate.symbol,
        name=candidate.name,
        theme=candidate.theme,
        decision=_decision(candidate, phase, lifecycle),
        priority_score=_priority_score(candidate, status, market_pulses, phase, lifecycle),
        last_close=candidate.last_close,
        entry_plan=_entry_plan(candidate, lifecycle, execution),
        invalidation=_invalidation(candidate, execution),
        position_note=_position_note(candidate, lifecycle, execution),
        evidence=[*_evidence(candidate, status, market_pulses, lifecycle), f"主题价格阶段：{phase}"],
        risk_notes=_risk_notes(candidate),
        lifecycle_stage=lifecycle.stage if lifecycle else "阶段未确认",
        independence_status=lifecycle.independence_status if lifecycle else "随市主线",
        entry_mode=execution.entry_mode,
        entry_zone_low=execution.entry_zone_low,
        entry_zone_high=execution.entry_zone_high,
        confirm_price=execution.confirm_price,
        stop_price=execution.stop_price,
        valid_for_days=execution.valid_for_days,
        max_hold_days=execution.max_hold_days,
        max_position_fraction=execution.max_position_fraction,
        initial_position_fraction=execution.initial_position_fraction,
    )


def _theme_groups(
    plans: list[NextBuyPlan],
    themes: list[ThemeSnapshot],
    lifecycle_by_theme: dict[str, ThemeLifecycleSignal],
    per_theme_limit: int = 3,
) -> list[ThemeBuyGroup]:
    grouped: dict[str, list[NextBuyPlan]] = {}
    for plan in plans:
        grouped.setdefault(plan.theme, []).append(plan)

    status_by_theme = {theme.name: theme.status for theme in themes}
    active_statuses = {"主线成立", "主线候选", "轮动观察"}
    ordered_theme_names = [theme.name for theme in themes[:4] if theme.status in active_statuses]
    ordered_theme_names.extend(
        theme.name for theme in themes if theme.name in grouped and theme.name not in ordered_theme_names
    )
    ordered_theme_names.extend(
        sorted(theme for theme in grouped if theme not in status_by_theme and theme not in ordered_theme_names)
    )

    result: list[ThemeBuyGroup] = []
    for theme_name in ordered_theme_names:
        lifecycle = lifecycle_by_theme.get(theme_name)
        theme_plans = grouped.get(theme_name, [])[:per_theme_limit]
        result.append(
            ThemeBuyGroup(
                theme=theme_name,
                theme_status=status_by_theme.get(theme_name, "未知"),
                plans=theme_plans,
                lifecycle_stage=lifecycle.stage if lifecycle else "阶段未确认",
                independence_status=lifecycle.independence_status if lifecycle else "随市主线",
                note=None if theme_plans else "当前没有个股通过强度、位置和回测门槛。",
            )
        )
    return result


def build_next_buy_report(
    candidates: list[StrongStockCandidate],
    themes: list[ThemeSnapshot],
    market_pulses: list[MarketPulse],
    trading_gate: TradingGate | None = None,
    limit: int = 3,
    theme_lifecycle: ThemeLifecycleReport | None = None,
) -> NextBuyReport:
    lifecycle_by_theme = {signal.theme: signal for signal in (theme_lifecycle.signals if theme_lifecycle else [])}
    plans = [
        _build_plan(candidate, themes, market_pulses, lifecycle_by_theme.get(candidate.theme))
        for candidate in candidates
    ]
    plans = [plan for plan in plans if plan.priority_score >= 60]
    plans.sort(key=lambda item: item.priority_score, reverse=True)
    actionable_decisions = {
        "优先候选，等待回踩",
        "突破确认候选",
        "优先候选，分批确认",
        "主升加速，等待回踩",
    }
    actionable_plans = [plan for plan in plans if plan.decision in actionable_decisions]
    notes = [
        "系统输出的是下一笔优先候选和条件化交易计划，不是无条件市价买入指令。",
        "若主线强度、市场环境或个股触发条件变弱，候选应自动降级。",
        "触发采用收盘确认、下一交易日开盘执行；封死涨停不买，封死跌停不假设能够卖出。",
    ]
    by_theme = _theme_groups(plans, themes, lifecycle_by_theme)
    if not plans:
        return NextBuyReport(
            primary=None,
            alternatives=[],
            by_theme=by_theme,
            notes=[*notes, "当前没有达到阈值的下一笔买入候选。"],
        )
    if trading_gate and trading_gate.level == "red":
        return NextBuyReport(
            primary=None,
            alternatives=[],
            by_theme=by_theme,
            notes=[*notes, f"市场交易闸门为“{trading_gate.state}”，顺势候选全部转入等待确认。"],
        )
    if not actionable_plans:
        return NextBuyReport(
            primary=None,
            alternatives=[],
            by_theme=by_theme,
            notes=[*notes, "候选存在，但均触发了基本面、预期差、生命周期或价格阶段约束，只进入等待区。"],
        )
    return NextBuyReport(
        primary=actionable_plans[0],
        alternatives=actionable_plans[1:limit],
        by_theme=by_theme,
        notes=notes,
    )
