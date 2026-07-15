from __future__ import annotations

from statistics import mean
from typing import Any

from .models import KlineSeries, MarketStructure


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def _ratio(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def _rolling_ma(values: list[float], end: int, window: int) -> float | None:
    start = end - window + 1
    if start < 0:
        return None
    return _avg(values[start : end + 1])


def _index_signal(series: KlineSeries) -> dict[str, bool | float] | None:
    count = min(len(series.close), len(series.high), len(series.low), len(series.amount))
    if count < 35:
        return None
    close = series.close[-count:]
    high = series.high[-count:]
    low = series.low[-count:]
    amount = series.amount[-count:]
    ma5 = _avg(close[-5:])
    ma10 = _avg(close[-10:])
    ma20 = _avg(close[-20:])
    ma30 = _avg(close[-30:])
    previous_ma5 = _avg(close[-6:-1])
    previous_ma10 = _avg(close[-11:-1])
    prior_amount20 = _avg(amount[-21:-1])
    recent_amount3 = _avg(amount[-3:])
    if None in (ma5, ma10, ma20, ma30, previous_ma5, previous_ma10, prior_amount20, recent_amount3):
        return None
    assert ma5 is not None and ma10 is not None and ma20 is not None and ma30 is not None
    assert previous_ma5 is not None and previous_ma10 is not None
    assert prior_amount20 is not None and recent_amount3 is not None
    amount_ratio = amount[-1] / prior_amount20 if prior_amount20 else 0.0
    recent_amount_ratio = recent_amount3 / prior_amount20 if prior_amount20 else 0.0
    ret_1d = close[-1] / close[-2] - 1 if close[-2] else 0.0
    bullish_alignment = close[-1] > ma5 > ma10 and ma5 > previous_ma5 and ma10 >= previous_ma10
    volume_confirmation = bool(
        close[-1] > ma20
        and (
            (ret_1d >= 0.012 and amount_ratio >= 1.20)
            or (recent_amount_ratio >= 1.05 and close[-1] > ma10)
        )
    )
    higher_structure = max(high[-10:]) > max(high[-20:-10]) and min(low[-10:]) > min(low[-20:-10])
    below_ma20: list[bool] = []
    for idx in range(count - 3, count):
        rolling = _rolling_ma(close, idx, 20)
        below_ma20.append(bool(rolling is not None and close[idx] < rolling))
    confirmed_breakdown = all(below_ma20)
    false_break_watch = not below_ma20[-1] and any(below_ma20[:-1])
    return {
        "above_ma5": close[-1] > ma5,
        "above_ma20": close[-1] > ma20,
        "bullish_alignment": bullish_alignment,
        "volume_confirmation": volume_confirmation,
        "higher_structure": higher_structure,
        "confirmed_breakdown": confirmed_breakdown,
        "false_break_watch": false_break_watch,
        "amount_ratio": amount_ratio,
    }


def build_market_structure(theme_config: dict[str, Any], klines: dict[str, KlineSeries]) -> MarketStructure:
    symbols: list[str] = []
    for group in theme_config.get("market_context_groups", []):
        if group.get("name") == "A股宽基环境":
            symbols = [str(symbol) for symbol in group.get("symbols", [])[:3]]
            break
    signals = [signal for symbol in symbols if (series := klines.get(symbol)) and (signal := _index_signal(series))]
    if not signals:
        return MarketStructure(
            status="结构数据不足",
            score=35.0,
            index_count=0,
            above_ma5_ratio=None,
            above_ma20_ratio=None,
            bullish_alignment_ratio=None,
            volume_confirmation_ratio=None,
            higher_high_low_ratio=None,
            confirmed_breakdown_ratio=None,
            evidence=["三大指数日线不足35根，无法验证底部与破位结构"],
        )

    above_ma5 = _ratio([bool(item["above_ma5"]) for item in signals])
    above_ma20 = _ratio([bool(item["above_ma20"]) for item in signals])
    alignment = _ratio([bool(item["bullish_alignment"]) for item in signals])
    volume = _ratio([bool(item["volume_confirmation"]) for item in signals])
    higher = _ratio([bool(item["higher_structure"]) for item in signals])
    breakdown = _ratio([bool(item["confirmed_breakdown"]) for item in signals])
    false_break = _ratio([bool(item["false_break_watch"]) for item in signals])
    score = 20.0
    score += 15.0 * (above_ma5 or 0.0)
    score += 20.0 * (above_ma20 or 0.0)
    score += 18.0 * (alignment or 0.0)
    score += 17.0 * (volume or 0.0)
    score += 15.0 * (higher or 0.0)
    score -= 25.0 * (breakdown or 0.0)
    score = round(max(0.0, min(100.0, score)), 2)

    if breakdown is not None and breakdown >= 2 / 3:
        status = "破位确认"
    elif false_break is not None and false_break >= 1 / 3:
        status = "破位观察"
    elif volume is not None and higher is not None and alignment is not None and volume >= 2 / 3 and higher >= 2 / 3 and alignment >= 2 / 3:
        status = "右侧确认"
    elif above_ma20 is not None and alignment is not None and higher is not None and above_ma20 >= 2 / 3 and alignment >= 2 / 3 and higher >= 2 / 3:
        status = "上升趋势"
    elif above_ma5 is not None and above_ma20 is not None and above_ma5 <= 1 / 3 and above_ma20 <= 1 / 3:
        status = "底部未确认"
    else:
        status = "筑底观察"

    evidence = [
        f"站上5日线指数 {above_ma5 * 100:.0f}%" if above_ma5 is not None else "5日线数据不足",
        f"站上20日线指数 {above_ma20 * 100:.0f}%" if above_ma20 is not None else "20日线数据不足",
        f"均线转强指数 {alignment * 100:.0f}%" if alignment is not None else "均线数据不足",
        f"持续量价确认指数 {volume * 100:.0f}%" if volume is not None else "成交数据不足",
        f"高点/低点同步抬高指数 {higher * 100:.0f}%" if higher is not None else "结构数据不足",
        f"连续3日跌破20日线指数 {breakdown * 100:.0f}%" if breakdown is not None else "破位数据不足",
    ]
    return MarketStructure(
        status=status,
        score=score,
        index_count=len(signals),
        above_ma5_ratio=above_ma5,
        above_ma20_ratio=above_ma20,
        bullish_alignment_ratio=alignment,
        volume_confirmation_ratio=volume,
        higher_high_low_ratio=higher,
        confirmed_breakdown_ratio=breakdown,
        evidence=evidence,
    )
