from __future__ import annotations

from statistics import mean

from .models import AccumulationCandidate, AccumulationReport, KlineSeries, SymbolSnapshot, ThemeSnapshot, safe_change


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def _fmt_price(value: float) -> str:
    return f"{value:.2f}"


def _ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)


def _stock_like(symbol: str, name: str) -> bool:
    upper_name = name.upper()
    if symbol.endswith(".US") or symbol.endswith(".HK"):
        return False
    if any(token in upper_name for token in ("ETF", "LOF", "REIT")):
        return False
    if any(token in name for token in ("指数", "基金", "转债", "退")):
        return False
    if "ST" in upper_name:
        return False
    return symbol.endswith(".SH") or symbol.endswith(".SZ")


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _primary_theme(theme_names: list[str], theme_rank: dict[str, int]) -> str:
    if not theme_names:
        return "未映射"
    return sorted(theme_names, key=lambda item: theme_rank.get(item, 999))[0]


def _theme_bonus(theme_names: list[str], status_by_theme: dict[str, str]) -> float:
    best = 0.0
    for theme in theme_names:
        status = status_by_theme.get(theme)
        if status == "主线成立":
            best = max(best, 4.0)
        elif status == "主线候选":
            best = max(best, 3.0)
        elif status == "轮动观察":
            best = max(best, 1.5)
    return best


def _classify(score: float, amount_ratio_5_20: float, amount_ratio_10_30: float, ret_5d: float | None, above_ma10: bool) -> str:
    if score >= 72 and amount_ratio_5_20 >= 1.22 and ret_5d is not None and ret_5d >= 0.015 and above_ma10:
        return "低位放量转强"
    if score >= 64 and (amount_ratio_5_20 >= 1.12 or amount_ratio_10_30 >= 1.06):
        return "低位资金试探"
    return "低位观察"


def _score(
    range_position_60d: float,
    drawdown_60d: float,
    ret_5d: float | None,
    ret_20d: float | None,
    amount_ratio_5_20: float,
    amount_ratio_10_30: float,
    above_ma10: bool,
    above_ma20: bool,
    ma10_turning: bool,
    theme_bonus: float,
) -> float:
    score = 24.0
    score += _clip((0.58 - range_position_60d) / 0.58, 0.0, 1.0) * 18.0
    score += _clip(abs(min(drawdown_60d, 0.0)) / 0.28, 0.0, 1.0) * 8.0
    score += _clip((amount_ratio_5_20 - 1.0) / 0.35, -0.5, 1.0) * 14.0
    score += _clip((amount_ratio_10_30 - 1.0) / 0.18, -0.5, 1.0) * 8.0

    if ret_5d is not None:
        score += _clip(ret_5d / 0.08, -1.0, 1.0) * 8.0
    if ret_20d is not None:
        if ret_20d >= -0.05:
            score += 3.0
        else:
            score -= _clip(abs(ret_20d + 0.05) / 0.12, 0.0, 1.0) * 6.0

    if above_ma10:
        score += 3.0
    if above_ma20:
        score += 2.0
    if ma10_turning:
        score += 3.0
    score += theme_bonus
    return round(_clip(score, 0.0, 100.0), 2)


def _candidate_from_series(
    snapshot: SymbolSnapshot,
    series: KlineSeries,
    theme_rank: dict[str, int],
    status_by_theme: dict[str, str],
) -> AccumulationCandidate | None:
    if not _stock_like(snapshot.symbol, snapshot.name):
        return None

    bar_count = min(len(series.close), len(series.high), len(series.low), len(series.amount))
    if bar_count < 60:
        return None

    close = series.close[-bar_count:]
    high = series.high[-bar_count:]
    low = series.low[-bar_count:]
    amount = series.amount[-bar_count:]
    last_close = close[-1]

    high_60d = max(high[-60:])
    low_60d = min(low[-60:])
    if high_60d <= low_60d or last_close <= 0:
        return None

    range_position_60d = (last_close - low_60d) / (high_60d - low_60d)
    drawdown_60d = safe_change(last_close, high_60d)
    if drawdown_60d is None:
        return None

    amount_ma5 = _avg(amount[-5:])
    amount_ma10 = _avg(amount[-10:])
    amount_ma20 = _avg(amount[-20:])
    amount_ma30 = _avg(amount[-30:])
    if not amount_ma5 or not amount_ma10 or not amount_ma20 or not amount_ma30:
        return None
    amount_ratio_5_20 = amount_ma5 / amount_ma20
    amount_ratio_10_30 = amount_ma10 / amount_ma30

    ret_5d = safe_change(last_close, close[-6]) if len(close) >= 6 else None
    ret_20d = safe_change(last_close, close[-21]) if len(close) >= 21 else None
    ma10 = _avg(close[-10:])
    ma20 = _avg(close[-20:])
    ma10_prev = _avg(close[-15:-5]) if len(close) >= 15 else None
    if ma10 is None or ma20 is None:
        return None

    recent_floor = min(low[-10:])
    above_ma10 = last_close >= ma10
    above_ma20 = last_close >= ma20
    ma10_turning = ma10_prev is not None and ma10 >= ma10_prev

    low_position = range_position_60d <= 0.58 or drawdown_60d <= -0.12
    volume_turn = amount_ratio_5_20 >= 1.08 or amount_ratio_10_30 >= 1.04
    stabilizing = (
        ret_5d is not None
        and ret_5d >= -0.03
        and (ret_20d is None or ret_20d >= -0.22)
        and last_close >= recent_floor * 1.01
    )
    if not (low_position and volume_turn and stabilizing):
        return None

    score = _score(
        range_position_60d=range_position_60d,
        drawdown_60d=drawdown_60d,
        ret_5d=ret_5d,
        ret_20d=ret_20d,
        amount_ratio_5_20=amount_ratio_5_20,
        amount_ratio_10_30=amount_ratio_10_30,
        above_ma10=above_ma10,
        above_ma20=above_ma20,
        ma10_turning=ma10_turning,
        theme_bonus=_theme_bonus(snapshot.themes, status_by_theme),
    )
    if score < 58:
        return None

    ma20_distance = safe_change(last_close, ma20)
    trigger_price = max(last_close * 1.018, ma20 * 1.01)
    support_price = min(recent_floor, ma20 * 0.97)
    if above_ma20:
        entry_plan = (
            f"先看回踩不破20日线附近 {_fmt_price(ma20)} 且成交额不明显萎缩；"
            f"若放量突破 {_fmt_price(trigger_price)}，再按试错仓确认。"
        )
    else:
        entry_plan = (
            f"先等放量站回20日线 {_fmt_price(ma20)} 上方；"
            f"未站回前只观察，不把低位当成买点。"
        )
    invalidation = (
        f"跌破近10日低点/20日线防守区 {_fmt_price(support_price)}，"
        "或5日/20日成交额比回落到1倍以下，资金介入假设降级。"
    )

    reasons = [
        f"60日区间位置 {range_position_60d * 100:.1f}%",
        f"距60日高点 {drawdown_60d * 100:.2f}%",
        f"5日/20日成交额 {amount_ratio_5_20:.2f}x",
        f"10日/30日成交额 {amount_ratio_10_30:.2f}x",
    ]
    if ret_5d is not None:
        reasons.append(f"5日涨幅 {ret_5d * 100:.2f}%")
    if ret_20d is not None:
        reasons.append(f"20日涨幅 {ret_20d * 100:.2f}%")
    if above_ma10:
        reasons.append("收盘站上10日均线")
    if ma10_turning:
        reasons.append("10日均线走平/抬升")

    return AccumulationCandidate(
        symbol=snapshot.symbol,
        name=snapshot.name,
        themes=snapshot.themes,
        primary_theme=_primary_theme(snapshot.themes, theme_rank),
        status=_classify(score, amount_ratio_5_20, amount_ratio_10_30, ret_5d, above_ma10),
        score=score,
        last_close=last_close,
        range_position_60d=range_position_60d,
        drawdown_60d=drawdown_60d,
        ret_5d=ret_5d,
        ret_20d=ret_20d,
        amount_ratio_5_20=_ratio(amount_ratio_5_20),
        amount_ratio_10_30=_ratio(amount_ratio_10_30),
        ma20_distance=ma20_distance,
        entry_plan=entry_plan,
        invalidation=invalidation,
        reasons=reasons,
    )


def build_accumulation_report(
    snapshots: dict[str, SymbolSnapshot],
    klines: dict[str, KlineSeries],
    themes: list[ThemeSnapshot],
    max_candidates: int = 12,
) -> AccumulationReport:
    theme_rank = {theme.name: idx for idx, theme in enumerate(themes)}
    status_by_theme = {theme.name: theme.status for theme in themes}
    candidates: list[AccumulationCandidate] = []
    for symbol, snapshot in snapshots.items():
        series = klines.get(symbol)
        if series is None:
            continue
        candidate = _candidate_from_series(snapshot, series, theme_rank, status_by_theme)
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(key=lambda item: item.score, reverse=True)
    notes = [
        "低位资金介入候选不是追强榜，定位是观察/试错池。",
        "低位条件同时看60日位置、距高点回撤、成交额均线抬升和短线止跌，不把单纯下跌当机会。",
    ]
    if not candidates:
        notes.append("当前扫描范围内没有同时满足低位、放量和止跌条件的股票。")
    return AccumulationReport(candidates=candidates[:max_candidates], notes=notes)
