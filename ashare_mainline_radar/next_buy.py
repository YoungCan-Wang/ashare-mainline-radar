from __future__ import annotations

from .models import MarketPulse, NextBuyPlan, NextBuyReport, StrongStockCandidate, ThemeBuyGroup, ThemeSnapshot


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


def _priority_score(candidate: StrongStockCandidate, theme_status: str, market_pulses: list[MarketPulse]) -> float:
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
    return round(max(0.0, min(100.0, score)), 2)


def _decision(candidate: StrongStockCandidate) -> str:
    if candidate.ret_5d is not None and candidate.ret_5d >= 0.15:
        return "优先候选，等待回踩"
    if candidate.status == "突破观察":
        return "突破确认候选"
    return "优先候选，分批确认"


def _entry_plan(candidate: StrongStockCandidate) -> str:
    close = candidate.last_close
    pullback_low = close * 0.955
    pullback_high = close * 0.985
    breakout = close * 1.012
    if candidate.ret_5d is not None and candidate.ret_5d >= 0.15:
        return (
            f"不追高；优先等回踩到 {_fmt_price(pullback_low)}-{_fmt_price(pullback_high)} 区间后企稳，"
            "或盘中缩量回踩后重新放量转强再分批。"
        )
    if candidate.status == "突破观察":
        return f"放量站上 {_fmt_price(breakout)} 附近并保持主线强度时再确认；否则等回踩到 {_fmt_price(pullback_high)} 附近。"
    return f"可用小仓试探，优先等 {_fmt_price(pullback_high)} 附近回踩不破后再加仓。"


def _invalidation(candidate: StrongStockCandidate) -> str:
    close = candidate.last_close
    hard_stop = close * 0.92
    soft_stop = close * 0.95
    return f"跌破 {_fmt_price(soft_stop)} 先降级观察；有效跌破 {_fmt_price(hard_stop)} 或主线退出前三，视为交易假设失效。"


def _position_note(candidate: StrongStockCandidate) -> str:
    backtest = candidate.backtest
    if backtest and backtest.worst_return is not None and backtest.worst_return < -0.12:
        return "历史最差信号回撤较大，单票建议轻仓分批，首笔不超过计划仓位的 1/3。"
    return "首笔按试错仓处理，确认主线延续和个股不破失效位后再加仓。"


def _evidence(candidate: StrongStockCandidate, theme_status: str, market_pulses: list[MarketPulse]) -> list[str]:
    evidence = [f"{candidate.theme}：{theme_status}", f"个股状态：{candidate.status}，强度 {candidate.score:.1f}"]
    if candidate.ret_5d is not None:
        evidence.append(f"5日涨幅 {candidate.ret_5d * 100:.2f}%")
    if candidate.ret_20d is not None:
        evidence.append(f"20日涨幅 {candidate.ret_20d * 100:.2f}%")
    if candidate.amount_ratio is not None:
        evidence.append(f"成交热度 {candidate.amount_ratio:.2f}x")
    if candidate.backtest:
        win = "n/a" if candidate.backtest.win_rate is None else f"{candidate.backtest.win_rate * 100:.1f}%"
        avg = "n/a" if candidate.backtest.avg_return is None else f"{candidate.backtest.avg_return * 100:.2f}%"
        evidence.append(f"历史信号 {candidate.backtest.signals} 次，胜率 {win}，均值 {avg}")
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
    return notes


def _build_plan(candidate: StrongStockCandidate, themes: list[ThemeSnapshot], market_pulses: list[MarketPulse]) -> NextBuyPlan:
    status = _theme_status(candidate.theme, themes)
    return NextBuyPlan(
        symbol=candidate.symbol,
        name=candidate.name,
        theme=candidate.theme,
        decision=_decision(candidate),
        priority_score=_priority_score(candidate, status, market_pulses),
        last_close=candidate.last_close,
        entry_plan=_entry_plan(candidate),
        invalidation=_invalidation(candidate),
        position_note=_position_note(candidate),
        evidence=_evidence(candidate, status, market_pulses),
        risk_notes=_risk_notes(candidate),
    )


def _theme_groups(plans: list[NextBuyPlan], themes: list[ThemeSnapshot], per_theme_limit: int = 3) -> list[ThemeBuyGroup]:
    grouped: dict[str, list[NextBuyPlan]] = {}
    for plan in plans:
        grouped.setdefault(plan.theme, []).append(plan)

    status_by_theme = {theme.name: theme.status for theme in themes}
    ordered_theme_names = [theme.name for theme in themes if theme.name in grouped]
    ordered_theme_names.extend(sorted(theme for theme in grouped if theme not in status_by_theme))

    return [
        ThemeBuyGroup(
            theme=theme_name,
            theme_status=status_by_theme.get(theme_name, "未知"),
            plans=grouped[theme_name][:per_theme_limit],
        )
        for theme_name in ordered_theme_names
    ]


def build_next_buy_report(
    candidates: list[StrongStockCandidate],
    themes: list[ThemeSnapshot],
    market_pulses: list[MarketPulse],
    limit: int = 3,
) -> NextBuyReport:
    plans = [_build_plan(candidate, themes, market_pulses) for candidate in candidates]
    plans = [plan for plan in plans if plan.priority_score >= 60]
    plans.sort(key=lambda item: item.priority_score, reverse=True)
    notes = [
        "系统输出的是下一笔优先候选和条件化交易计划，不是无条件市价买入指令。",
        "若主线强度、市场环境或个股触发条件变弱，候选应自动降级。",
    ]
    by_theme = _theme_groups(plans, themes)
    if not plans:
        return NextBuyReport(primary=None, alternatives=[], by_theme=[], notes=[*notes, "当前没有达到阈值的下一笔买入候选。"])
    return NextBuyReport(primary=plans[0], alternatives=plans[1:limit], by_theme=by_theme, notes=notes)
