from __future__ import annotations

from statistics import mean

from .models import (
    FundamentalReport,
    GoldenPitCandidate,
    GoldenPitReport,
    KlineSeries,
    SymbolSnapshot,
    ThemeSnapshot,
    TradingGate,
    safe_change,
)
from .strategy_rules import theme_crowding_blocks_entry


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _stock_like(symbol: str, name: str) -> bool:
    upper = name.upper()
    return (
        (symbol.endswith(".SH") or symbol.endswith(".SZ"))
        and not any(token in upper for token in ("ETF", "LOF", "REIT", "ST"))
        and not any(token in name for token in ("指数", "基金", "转债", "退"))
    )


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def _macd_contracting(values: list[float]) -> bool:
    if len(values) < 35:
        return False
    fast = _ema(values, 12)
    slow = _ema(values, 26)
    diff = [fast_value - slow_value for fast_value, slow_value in zip(fast, slow)]
    signal = _ema(diff, 9)
    histogram = [2 * (diff_value - signal_value) for diff_value, signal_value in zip(diff, signal)]
    return histogram[-1] >= 0 or histogram[-1] > histogram[-2] > histogram[-3]


def _distribution_risk(
    high: list[float], low: list[float], amount: list[float], last: float, ma10: float
) -> bool:
    recent_amount = _avg(amount[-5:])
    prior_amount = _avg(amount[-20:-5])
    return bool(
        recent_amount
        and prior_amount
        and recent_amount >= prior_amount * 1.15
        and last < ma10
        and max(high[-5:]) < max(high[-10:-5])
        and min(low[-5:]) < min(low[-10:-5])
    )


def _candidate(
    snapshot: SymbolSnapshot,
    series: KlineSeries,
    theme: ThemeSnapshot,
    broad_ret_1d: float | None,
    broad_ret_5d: float | None,
    fundamentals: FundamentalReport | None,
    gate: TradingGate,
) -> GoldenPitCandidate | None:
    if not _stock_like(snapshot.symbol, snapshot.name) or len(series.close) < 60:
        return None
    close, high, low, amount = series.close, series.high, series.low, series.amount
    last = close[-1]
    high_20 = max(high[-20:])
    drawdown = safe_change(last, high_20)
    if drawdown is None or not (-0.20 <= drawdown <= -0.045):
        return None

    ma10 = _avg(close[-10:])
    ma20 = _avg(close[-20:])
    ma60 = _avg(close[-60:])
    ma5 = _avg(close[-5:])
    previous_ma5 = _avg(close[-6:-1])
    prior_amount_5 = _avg(amount[-6:-1])
    if ma5 is None or previous_ma5 is None or ma10 is None or ma20 is None or ma60 is None or not prior_amount_5:
        return None
    if last < ma60 * 0.97 or (snapshot.ret_5d is not None and snapshot.ret_5d < -0.13):
        return None

    relative_1d = None if snapshot.ret_1d is None or broad_ret_1d is None else snapshot.ret_1d - broad_ret_1d
    relative_5d = None if snapshot.ret_5d is None or broad_ret_5d is None else snapshot.ret_5d - broad_ret_5d
    amount_ratio_1_5 = amount[-1] / prior_amount_5
    day_range = high[-1] - low[-1]
    close_location = (last - low[-1]) / day_range if day_range > 0 else 0.5
    absorption = amount_ratio_1_5 >= 1.05 and close_location >= 0.55
    resilient = bool(
        (relative_1d is not None and relative_1d >= 0.01)
        or (relative_5d is not None and relative_5d >= 0.025)
    )
    reclaim = last > close[-2] and last >= ma10 and amount_ratio_1_5 >= 1.05
    ma5_flattening = ma5 >= previous_ma5 * 0.997
    no_new_low = min(low[-3:]) >= min(low[-10:-3])
    macd_contracting = _macd_contracting(close)
    distribution_risk = _distribution_risk(high, low, amount, last, ma10)
    bottom_confirmation_score = sum((ma5_flattening, no_new_low, macd_contracting))
    if distribution_risk or not (absorption or resilient or reclaim) or bottom_confirmation_score < 1:
        return None

    fundamental = None
    if fundamentals:
        fundamental = next((item for item in fundamentals.snapshots if item.symbol == snapshot.symbol), None)
    fundamental_status = fundamental.status if fundamental else "未覆盖"
    if fundamental_status == "基本面拖累":
        return None

    score = 48.0
    score += 10.0 if theme.status == "主线成立" else 6.0
    score += _clip((abs(drawdown) - 0.045) / 0.10, 0.0, 1.0) * 8.0
    score += _clip((last / ma60 - 0.97) / 0.08, 0.0, 1.0) * 7.0
    if relative_1d is not None:
        score += _clip(relative_1d / 0.04, -1.0, 1.0) * 8.0
    if relative_5d is not None:
        score += _clip(relative_5d / 0.08, -1.0, 1.0) * 6.0
    if absorption:
        score += 6.0
    if reclaim:
        score += 7.0
    score += bottom_confirmation_score * 2.0
    if fundamental:
        score += _clip((fundamental.score - 60.0) / 30.0, -1.0, 1.0) * 5.0
    score = round(_clip(score, 0.0, 100.0), 2)
    if score < 62:
        return None

    stage = "止跌确认" if reclaim and bottom_confirmation_score >= 2 else "坑位形成"
    trigger = max(high[-1] * 1.003, ma10 * 1.005)
    structural_stop = min(low[-7:]) * 0.985
    stop = max(structural_stop, last * 0.92)
    action = "触发后可列入试错仓" if gate.level != "red" and stage == "止跌确认" else "只观察，等待确认"
    confirmation_prefix = "当前不执行；待交易闸门恢复后，" if gate.level == "red" else ""
    reasons = [
        f"属于前三主线 {theme.name}（{theme.status}）",
        f"距20日高点 {drawdown * 100:.2f}%",
        f"相对大盘单日强弱 {relative_1d * 100:.2f}pct" if relative_1d is not None else "大盘单日对照缺失",
        f"当日/前5日成交额 {amount_ratio_1_5:.2f}x",
        f"仍守在60日线的 {last / ma60 * 100:.1f}% 位置",
    ]
    if absorption:
        reasons.append("放量承接且收盘位于日内区间上半部")
    if reclaim:
        reasons.append("放量收复10日线，出现止跌确认")
    if ma5_flattening:
        reasons.append("5日均线走平/抬升")
    if macd_contracting:
        reasons.append("MACD下跌动能收缩")
    if no_new_low:
        reasons.append("近3日低点未再下破前期低点")
    if fundamental:
        reasons.append(f"{fundamental.status}，财务分 {fundamental.score:.1f}")

    return GoldenPitCandidate(
        symbol=snapshot.symbol,
        name=snapshot.name,
        theme=theme.name,
        stage=stage,
        score=score,
        last_close=last,
        drawdown_from_20d_high=drawdown,
        ret_1d=snapshot.ret_1d,
        ret_5d=snapshot.ret_5d,
        relative_1d=relative_1d,
        amount_ratio_1_5=round(amount_ratio_1_5, 4),
        ma20_distance=safe_change(last, ma20),
        fundamental_score=fundamental.score if fundamental else None,
        fundamental_status=fundamental_status,
        bottom_confirmation_score=bottom_confirmation_score,
        ma5_flattening=ma5_flattening,
        macd_contracting=macd_contracting,
        no_new_low=no_new_low,
        confirmation=(
            f"{confirmation_prefix}后续回踩不破10日线并放量站上 {trigger:.2f}，"
            "且5日线、MACD动能、近期低点至少两项继续改善，所属主线仍在前三；条件满足后再分批。"
        ),
        invalidation=f"有效跌破风险防守位 {stop:.2f}，或主线退出前三，黄金坑假设失效。",
        action=action,
        reasons=reasons,
    )


def build_golden_pit_report(
    snapshots: dict[str, SymbolSnapshot],
    klines: dict[str, KlineSeries],
    themes: list[ThemeSnapshot],
    gate: TradingGate,
    fundamentals: FundamentalReport | None = None,
    max_candidates: int = 8,
) -> GoldenPitReport:
    active = {
        theme.name: theme
        for theme in themes[:3]
        if theme.status in {"主线成立", "主线候选"}
        and not theme_crowding_blocks_entry(theme.price_phase)
    }
    broad_symbols = ("000001.SH", "399001.SZ", "399006.SZ")
    broad = [snapshots[symbol] for symbol in broad_symbols if symbol in snapshots]
    broad_ret_1d = _avg([item.ret_1d for item in broad if item.ret_1d is not None])
    broad_ret_5d = _avg([item.ret_5d for item in broad if item.ret_5d is not None])
    candidates: list[GoldenPitCandidate] = []
    for symbol, snapshot in snapshots.items():
        theme = next((active[name] for name in snapshot.themes if name in active), None)
        series = klines.get(symbol)
        if theme is None or series is None:
            continue
        item = _candidate(snapshot, series, theme, broad_ret_1d, broad_ret_5d, fundamentals, gate)
        if item:
            candidates.append(item)
    candidates.sort(key=lambda item: (item.stage == "止跌确认", item.score), reverse=True)
    notes = [
        "黄金坑不是单纯大跌：必须同时满足主线仍有效、回撤可控、中期趋势未破、相对大盘抗跌或出现承接。",
        "止跌确认还要求5日线走平、MACD下跌动能收缩、近期不再创新低至少满足两项。",
        "放量但价格高低点继续下移、且无法收复10日线时按派发/下跌中继处理，不进入黄金坑。",
        "山顶高拥挤主题不标记为黄金坑，避免把高位派发后的回撤误判为低风险坑位。",
        "坑位形成只进入观察池；止跌确认后仍要服从市场交易闸门和个股失效位。",
    ]
    if not candidates:
        notes.append("当前没有同时通过主线、趋势、相对强度和承接约束的黄金坑候选。")
    return GoldenPitReport(candidates=candidates[:max_candidates], notes=notes)
