from __future__ import annotations

from statistics import fmean
from typing import Any

from .models import KlineSeries, MonthlyBaseCandidate, MonthlyBaseReport, ThemeSnapshot, TradingGate

BOX_WINDOWS = (18, 24, 30)


def _quantile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _normalized_slope(values: list[float]) -> float:
    midpoint_x = (len(values) - 1) / 2
    midpoint_y = fmean(values)
    denominator = sum((index - midpoint_x) ** 2 for index in range(len(values)))
    if midpoint_y <= 0 or denominator == 0:
        return 0.0
    numerator = sum((index - midpoint_x) * (value - midpoint_y) for index, value in enumerate(values))
    return numerator / denominator / midpoint_y


def _stage(current: float, box_low: float, box_high: float, position: float) -> str:
    if current > box_high * 1.02:
        return "初步突破"
    if position >= 0.72:
        return "箱顶蓄势"
    if position <= 0.28:
        return "箱底观察"
    return "箱体中部"


def _trade_text(stage: str, box_low: float, box_high: float, gate: TradingGate) -> tuple[str, str, str]:
    if stage == "初步突破":
        action = f"等待日线放量站稳箱顶 {box_high:.2f}，或突破后回踩箱顶不破；确认前不追高。"
        confirmation = f"连续收盘保持在 {box_high:.2f} 上方，且回踩时成交缩、再转强时成交放大。"
    elif stage == "箱顶蓄势":
        action = f"靠近箱顶但尚未确认，等待放量突破 {box_high:.2f}，不在压力位直接抢跑。"
        confirmation = f"放量突破并站稳 {box_high:.2f}，或突破后第一次回踩不破箱顶。"
    elif stage == "箱底观察":
        action = f"只观察箱底承接；先等 {box_low:.2f} 附近止跌并重新站回短期均线。"
        confirmation = "日线不再创新低、成交回暖并形成更高低点后再评估。"
    else:
        action = "箱体中部赔率不清晰，等待回到箱底确认承接，或突破箱顶后再处理。"
        confirmation = f"回踩 {box_low:.2f} 附近止跌，或放量突破并站稳 {box_high:.2f}。"

    if gate.level == "red":
        action = f"市场闸门关闭，仅列观察。{action}"
    elif gate.level == "orange":
        action = f"市场只允许试错仓，仍需触发确认。{action}"
    invalidation = f"月线有效跌破箱底防守区 {box_low * 0.94:.2f}，或箱体下沿连续下移，长期蓄势假设失效。"
    return action, confirmation, invalidation


def detect_monthly_base(
    symbol: str,
    name: str,
    themes: list[str],
    series: KlineSeries,
    gate: TradingGate,
    active_theme_names: set[str] | None = None,
) -> MonthlyBaseCandidate | None:
    length = min(len(series.close), len(series.high), len(series.low), len(series.amount))
    if length < min(BOX_WINDOWS) + 1:
        return None

    closes = series.close[-length:]
    highs = series.high[-length:]
    lows = series.low[-length:]
    amounts = series.amount[-length:]
    current = closes[-1]
    candidates: list[MonthlyBaseCandidate] = []

    for months in BOX_WINDOWS:
        if length < months + 1:
            continue
        start = length - months - 1
        end = length - 1
        base_closes = closes[start:end]
        base_highs = highs[start:end]
        base_lows = lows[start:end]
        base_amounts = amounts[start:end]
        box_low = _quantile(base_lows, 0.20)
        box_high = _quantile(base_highs, 0.80)
        if box_low <= 0 or box_high <= box_low:
            continue

        span = box_high - box_low
        width = box_high / box_low - 1
        containment = sum(box_low * 0.95 <= close <= box_high * 1.05 for close in base_closes) / months
        slope = _normalized_slope(base_closes)
        net_change = abs(base_closes[-1] / base_closes[0] - 1)
        lower_touches = sum(value <= box_low + span * 0.22 for value in base_lows)
        upper_touches = sum(value >= box_high - span * 0.22 for value in base_highs)
        amount_contraction = fmean(base_amounts[-6:]) / fmean(base_amounts[:6]) if fmean(base_amounts[:6]) > 0 else 1.0
        prior_highs = highs[max(0, start - 60) : start]
        prior_peak_multiple = max(prior_highs, default=box_high) / ((box_low + box_high) / 2)

        if not (
            0.12 <= width <= 0.65
            and containment >= 0.82
            and abs(slope) <= 0.025
            and net_change <= 0.45
            and lower_touches >= 2
            and upper_touches >= 2
            and amount_contraction <= 1.30
            and box_low * 0.92 <= current <= box_high * 1.18
            and prior_peak_multiple < 2.20
        ):
            continue

        position = (current - box_low) / span
        stage = _stage(current, box_low, box_high, position)
        theme_bonus = 5.0 if active_theme_names and any(theme in active_theme_names for theme in themes) else 0.0
        score = min(
            100.0,
            30
            + containment * 25
            + max(0.0, 20 - abs(slope) * 500)
            + min(12.0, (lower_touches + upper_touches) * 1.2)
            + max(0.0, min(12.0, (1.20 - amount_contraction) * 20))
            + theme_bonus,
        )
        action, confirmation, invalidation = _trade_text(stage, box_low, box_high, gate)
        candidates.append(
            MonthlyBaseCandidate(
                symbol=symbol,
                name=name,
                themes=themes,
                stage=stage,
                score=score,
                box_months=months,
                box_low=box_low,
                box_high=box_high,
                box_width=width,
                last_close=current,
                box_position=position,
                monthly_slope=slope,
                amount_contraction=amount_contraction,
                prior_peak_multiple=prior_peak_multiple,
                action=action,
                confirmation=confirmation,
                invalidation=invalidation,
                reasons=[
                    f"{months}个月箱体收盘容纳率 {containment * 100:.0f}%",
                    f"月线斜率 {slope * 100:.2f}%/月",
                    f"上下沿触碰 {lower_touches}/{upper_touches} 次",
                    f"后6月/前6月成交额 {amount_contraction:.2f}x",
                ],
            )
        )

    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.score, item.box_months))


def build_monthly_base_report(
    monthly_klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    symbol_to_themes: dict[str, list[str]],
    themes: list[ThemeSnapshot],
    gate: TradingGate,
    max_candidates: int = 12,
) -> MonthlyBaseReport:
    active_theme_names = {theme.name for theme in themes[:3] if theme.status in {"主线成立", "主线候选"}}
    candidates: list[MonthlyBaseCandidate] = []
    for symbol, series in monthly_klines.items():
        instrument = instruments.get(symbol) or {}
        candidate = detect_monthly_base(
            symbol=symbol,
            name=str(instrument.get("name") or symbol),
            themes=symbol_to_themes.get(symbol, []),
            series=series,
            gate=gate,
            active_theme_names=active_theme_names,
        )
        if candidate is not None:
            candidates.append(candidate)

    stage_rank = {"初步突破": 0, "箱顶蓄势": 1, "箱底观察": 2, "箱体中部": 3}
    candidates.sort(key=lambda item: (stage_rank[item.stage], -item.score, -item.box_months))
    notes = [
        "长期箱体使用月线识别，与60日低位资金介入、主线急跌黄金坑分开统计。",
        "箱体只是研究观察池；必须等待日线突破或箱底止跌确认，不能把横盘本身当成买点。",
        "近60个月曾出现远高于当前箱体的大级别高点时直接排除，避免把长期下跌中继误判为蓄势。",
        "当月月K可能尚未走完，因此只用于定位；突破是否成立仍以收盘后的日线量价确认。",
    ]
    if not candidates:
        notes.append("当前扫描范围内没有同时通过箱体质量和历史主升排除条件的标的。")
    return MonthlyBaseReport(candidates=candidates[:max_candidates], notes=notes)
