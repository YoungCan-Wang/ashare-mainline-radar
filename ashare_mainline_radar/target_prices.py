from __future__ import annotations

import re
from statistics import median

from .models import (
    AccumulationCandidate,
    AccumulationReport,
    IntelItem,
    KlineSeries,
    ResearchTargetReference,
    StrongStockCandidate,
    StrongStockReport,
    TargetPriceEstimate,
    TargetPriceReport,
    ThemeSnapshot,
    safe_change,
)


TARGET_RE = re.compile(
    r"(?:目标价|目标价格|合理价值|合理价格|合理估值|目标区间|估值区间)"
    r"[^0-9]{0,16}"
    r"(\d+(?:\.\d+)?)"
    r"(?:\s*(?:-|~|至|到)\s*(\d+(?:\.\d+)?))?"
    r"\s*(?:元|人民币)?"
)


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_price(value: float) -> float:
    if value >= 100:
        return round(value, 1)
    return round(value, 2)


def _upside(target: float, last_close: float) -> float:
    return (target / last_close) - 1 if last_close else 0.0


def _reward_risk(upside: float, downside_to_stop: float) -> float | None:
    if downside_to_stop >= 0:
        return None
    risk = abs(downside_to_stop)
    if risk == 0:
        return None
    return round(upside / risk, 2)


def _series_context(series: KlineSeries) -> dict[str, float]:
    close = series.close
    high = series.high
    low = series.low
    high_20 = max(high[-20:])
    high_60 = max(high[-60:]) if len(high) >= 60 else high_20
    low_10 = min(low[-10:])
    low_20 = min(low[-20:])
    low_60 = min(low[-60:]) if len(low) >= 60 else low_20
    true_ranges: list[float] = []
    start = max(1, len(close) - 14)
    for idx in range(start, len(close)):
        previous_close = close[idx - 1]
        if previous_close <= 0:
            continue
        true_range = max(
            high[idx] - low[idx],
            abs(high[idx] - previous_close),
            abs(low[idx] - previous_close),
        )
        true_ranges.append(true_range / previous_close)
    atr_pct = _avg(true_ranges) or 0.03
    ma20 = _avg(close[-20:]) or close[-1]
    return {
        "last_close": close[-1],
        "high_20": high_20,
        "high_60": high_60,
        "low_10": low_10,
        "low_20": low_20,
        "low_60": low_60,
        "atr_pct": atr_pct,
        "ma20": ma20,
    }


def _matches_security(item: IntelItem, symbol: str, name: str) -> bool:
    code = symbol.split(".", 1)[0]
    text = f"{item.title} {item.summary or ''}"
    return code in text or name in text


def _research_targets_for(symbol: str, name: str, intel_items: list[IntelItem], limit: int = 3) -> list[ResearchTargetReference]:
    refs: list[ResearchTargetReference] = []
    for item in intel_items:
        if not _matches_security(item, symbol, name):
            continue
        text = f"{item.title} {item.summary or ''}"
        for match in TARGET_RE.finditer(text):
            low = float(match.group(1))
            high = float(match.group(2) or match.group(1))
            if low <= 0 or high <= 0:
                continue
            if high < low:
                low, high = high, low
            refs.append(
                ResearchTargetReference(
                    source=item.source,
                    title=item.title,
                    target_low=_round_price(low),
                    target_high=_round_price(high),
                    url=item.url,
                    published_at=item.published_at,
                )
            )
            break
        if len(refs) >= limit:
            break
    return refs


def _theme_status(theme_name: str, themes: list[ThemeSnapshot]) -> str:
    for theme in themes:
        if theme.name == theme_name:
            return theme.status
    return "未知"


def _confidence_for_strong(candidate: StrongStockCandidate, theme_status: str) -> str:
    backtest = candidate.backtest
    if (
        theme_status == "主线成立"
        and backtest
        and backtest.signals >= 5
        and backtest.win_rate is not None
        and backtest.win_rate >= 0.55
    ):
        return "中高"
    if backtest and backtest.signals >= 3:
        return "中"
    return "低"


def _strong_target(
    candidate: StrongStockCandidate,
    series: KlineSeries,
    themes: list[ThemeSnapshot],
    intel_items: list[IntelItem],
) -> TargetPriceEstimate:
    ctx = _series_context(series)
    last_close = candidate.last_close
    atr_pct = ctx["atr_pct"]
    backtest = candidate.backtest
    avg_return = backtest.avg_return if backtest and backtest.avg_return is not None else 0.04
    median_return = backtest.median_return if backtest and backtest.median_return is not None else avg_return
    ret_20d = candidate.ret_20d or 0.0
    projected_low = _clip(max(avg_return, median_return) * 1.3 + atr_pct, 0.06, 0.22)
    projected_high = _clip(projected_low + atr_pct * 2.2 + max(0.0, ret_20d) * 0.12, projected_low + 0.03, 0.38)
    target_low = max(last_close * (1 + projected_low), ctx["high_20"] * 1.01)
    target_high = max(target_low * 1.04, last_close * (1 + projected_high), ctx["high_60"] * 1.02)
    target_high = min(target_high, last_close * 1.5)
    stop_price = max(last_close * 0.92, ctx["low_20"] * 0.99)
    downside_to_stop = _upside(stop_price, last_close)
    refs = _research_targets_for(candidate.symbol, candidate.name, intel_items)
    theme_status = _theme_status(candidate.theme, themes)
    evidence = [
        f"{candidate.theme}：{theme_status}",
        f"20日高点 {ctx['high_20']:.2f}，60日高点 {ctx['high_60']:.2f}",
        f"14日均波动约 {atr_pct * 100:.2f}%",
    ]
    if backtest:
        avg = "n/a" if backtest.avg_return is None else f"{backtest.avg_return * 100:.2f}%"
        evidence.append(f"历史信号 {backtest.signals} 次，平均收益 {avg}")
    if refs:
        evidence.append("本地研报文本命中目标价，已列为参考")
    return TargetPriceEstimate(
        symbol=candidate.symbol,
        name=candidate.name,
        theme=candidate.theme,
        candidate_type="顺势强势",
        basis="研报目标+技术目标" if refs else "技术交易目标",
        horizon="2-8周交易目标",
        last_close=_round_price(last_close),
        target_low=_round_price(target_low),
        target_high=_round_price(target_high),
        upside_low=_upside(target_low, last_close),
        upside_high=_upside(target_high, last_close),
        stop_price=_round_price(stop_price),
        downside_to_stop=downside_to_stop,
        reward_risk_low=_reward_risk(_upside(target_low, last_close), downside_to_stop),
        reward_risk_high=_reward_risk(_upside(target_high, last_close), downside_to_stop),
        confidence=_confidence_for_strong(candidate, theme_status),
        evidence=evidence,
        research_targets=refs,
    )


def _confidence_for_accumulation(candidate: AccumulationCandidate) -> str:
    if candidate.score >= 82 and candidate.ma20_distance is not None and candidate.ma20_distance >= 0:
        return "中"
    return "低"


def _accumulation_target(
    candidate: AccumulationCandidate,
    series: KlineSeries,
    intel_items: list[IntelItem],
) -> TargetPriceEstimate:
    ctx = _series_context(series)
    last_close = candidate.last_close
    high_60 = ctx["high_60"]
    gap_to_high = max(0.0, high_60 - last_close)
    if gap_to_high > 0:
        target_low = last_close + gap_to_high * 0.45
        target_high = last_close + gap_to_high * 0.72
    else:
        target_low = last_close * 1.08
        target_high = last_close * 1.18
    target_low = max(target_low, last_close * 1.06, ctx["ma20"] * 1.03)
    target_high = max(target_high, target_low * 1.06)
    target_high = min(target_high, last_close * 1.42)
    stop_price = min(ctx["low_10"], ctx["ma20"] * 0.97)
    downside_to_stop = _upside(stop_price, last_close)
    refs = _research_targets_for(candidate.symbol, candidate.name, intel_items)
    evidence = [
        f"60日区间位置 {candidate.range_position_60d * 100:.1f}%" if candidate.range_position_60d is not None else "60日区间位置 n/a",
        f"距60日高点 {candidate.drawdown_60d * 100:.2f}%" if candidate.drawdown_60d is not None else "距60日高点 n/a",
        f"5日/20日成交额 {candidate.amount_ratio_5_20:.2f}x" if candidate.amount_ratio_5_20 is not None else "5日/20日成交额 n/a",
    ]
    if refs:
        evidence.append("本地研报文本命中目标价，已列为参考")
    return TargetPriceEstimate(
        symbol=candidate.symbol,
        name=candidate.name,
        theme=candidate.primary_theme,
        candidate_type="低位资金介入",
        basis="研报目标+压力位修复" if refs else "压力位修复目标",
        horizon="4-12周观察目标",
        last_close=_round_price(last_close),
        target_low=_round_price(target_low),
        target_high=_round_price(target_high),
        upside_low=_upside(target_low, last_close),
        upside_high=_upside(target_high, last_close),
        stop_price=_round_price(stop_price),
        downside_to_stop=downside_to_stop,
        reward_risk_low=_reward_risk(_upside(target_low, last_close), downside_to_stop),
        reward_risk_high=_reward_risk(_upside(target_high, last_close), downside_to_stop),
        confidence=_confidence_for_accumulation(candidate),
        evidence=evidence,
        research_targets=refs,
    )


def build_target_price_report(
    strong_stocks: StrongStockReport,
    accumulation: AccumulationReport,
    klines: dict[str, KlineSeries],
    intel_items: list[IntelItem],
    themes: list[ThemeSnapshot],
    max_estimates: int = 16,
) -> TargetPriceReport:
    estimates: list[TargetPriceEstimate] = []
    seen: set[str] = set()
    for candidate in strong_stocks.candidates:
        series = klines.get(candidate.symbol)
        if not series or candidate.symbol in seen:
            continue
        estimates.append(_strong_target(candidate, series, themes, intel_items))
        seen.add(candidate.symbol)

    for candidate in accumulation.candidates:
        series = klines.get(candidate.symbol)
        if not series or candidate.symbol in seen:
            continue
        estimates.append(_accumulation_target(candidate, series, intel_items))
        seen.add(candidate.symbol)

    estimates.sort(key=lambda item: (item.confidence != "中高", item.confidence != "中", -item.upside_low))
    notes = [
        "目标价是交易/研究目标区间，不等同于券商基于盈利预测和估值模型给出的正式目标价。",
        "若本地研报文本包含目标价或合理价值区间，系统会提取为研报参考；没有研报目标时只给技术目标。",
        "目标价必须和触发条件、失效价、仓位上限一起使用，不能单独作为买入理由。",
    ]
    return TargetPriceReport(estimates=estimates[:max_estimates], notes=notes)
