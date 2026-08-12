from __future__ import annotations

from typing import Any

from .config import theme_symbol_map
from .execution import daily_limit_price, price_limit_rate
from .models import (
    KlineSeries,
    PriceLimitBacktestCase,
    PriceLimitSignal,
    PriceLimitWatchReport,
    cn_market_date_from_ms,
)


EXECUTABLE_EVIDENCE_AS_OF = "2026-08-12"
EXECUTABLE_BACKTEST_CASES = [
    PriceLimitBacktestCase("首板确认后次日开盘追", "ceiling", 12_495, 0.4493, -0.0023, -0.0063, -0.1767, -0.0806),
    PriceLimitBacktestCase("主线首板确认后次日开盘追", "ceiling", 99, 0.4646, -0.0076, -0.0071, -0.1610, -0.0856),
    PriceLimitBacktestCase("高位连板确认后次日开盘追", "ceiling", 629, 0.4457, -0.0091, -0.0190, -0.2520, -0.1292),
    PriceLimitBacktestCase("跌停打开后次日开盘抄", "floor", 3_182, 0.4170, -0.0101, -0.0115, -0.1746, -0.0857),
    PriceLimitBacktestCase("主线跌停打开后次日开盘抄", "floor", 29, 0.4828, -0.0106, -0.0082, -0.1011, -0.0614),
    PriceLimitBacktestCase("封跌停后次日开盘抄", "floor", 4_321, 0.4016, -0.0124, -0.0163, -0.2021, -0.0976),
]


def _verdict(signal_type: str) -> str:
    if signal_type in {"天地板", "一字跌停", "收盘封跌停", "炸板"}:
        return "禁入"
    if signal_type in {"跌停打开", "地天板", "一字涨停"} or "板封住" in signal_type:
        return "不买"
    return "观察"


def _stock_name(instrument: dict[str, Any] | None, symbol: str) -> str:
    instrument = instrument or {}
    return str(instrument.get("name") or instrument.get("display_name") or symbol)


def _is_stock(symbol: str, instrument: dict[str, Any] | None) -> bool:
    if not symbol.endswith((".SH", ".SZ", ".BJ")):
        return False
    name = _stock_name(instrument, symbol).upper()
    return not any(token in name for token in ("ETF", "LOF", "REIT", "指数", "基金", "转债", "退"))


def _at_or_above(value: float, target: float) -> bool:
    return value >= target - 0.005


def _at_or_below(value: float, target: float) -> bool:
    return value <= target + 0.005


def _reference_close(series: KlineSeries, index: int) -> float:
    if index < len(series.prev_close) and series.prev_close[index] > 0:
        return series.prev_close[index]
    return series.close[index - 1]


def _within_first_five_listed_bars(
    series: KlineSeries, index: int, instrument: dict[str, Any] | None
) -> bool:
    ext = (instrument or {}).get("ext")
    listing_date = str(ext.get("listing_date")) if isinstance(ext, dict) and ext.get("listing_date") else None
    if not listing_date:
        return False
    first_date = cn_market_date_from_ms(series.timestamp[0]) if series.timestamp else None
    if first_date is None or listing_date < first_date:
        return False
    listed_indices = [
        cursor
        for cursor, timestamp in enumerate(series.timestamp[: index + 1])
        if (cn_market_date_from_ms(timestamp) or "") >= listing_date
    ]
    return index in listed_indices[:5]


def _closed_up(series: KlineSeries, index: int, upper: float) -> bool:
    return series.volume[index] > 0 and _at_or_above(series.high[index], upper) and _at_or_above(
        series.close[index], upper
    )


def _closed_down(series: KlineSeries, index: int, lower: float) -> bool:
    return series.volume[index] > 0 and _at_or_below(series.low[index], lower) and _at_or_below(
        series.close[index], lower
    )


def build_price_limit_watch(
    theme_config: dict[str, Any],
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    *,
    signal_limit: int = 20,
) -> PriceLimitWatchReport:
    """Summarize the latest completed daily price-limit behavior.

    The report describes closing-state observations only.  It never promotes a
    resealed ceiling or a broken floor into an executable intraday order.
    """

    latest_timestamp = max(
        (series.timestamp[-1] for series in klines.values() if series.timestamp),
        default=None,
    )
    as_of = cn_market_date_from_ms(latest_timestamp)
    symbol_themes = theme_symbol_map(theme_config)
    counts = {
        "limit_up_touches": 0,
        "closed_limit_up": 0,
        "first_board_closed": 0,
        "one_price_limit_up": 0,
        "broken_boards": 0,
        "ceiling_to_floor": 0,
        "limit_down_touches": 0,
        "closed_limit_down": 0,
        "one_price_limit_down": 0,
        "broken_floors": 0,
        "floor_to_ceiling": 0,
    }
    signals: list[PriceLimitSignal] = []

    for symbol, series in klines.items():
        instrument = instruments.get(symbol)
        if not _is_stock(symbol, instrument) or len(series.close) < 2 or not series.timestamp:
            continue
        index = len(series.close) - 1
        if latest_timestamp is None or series.timestamp[index] != latest_timestamp or series.volume[index] <= 0:
            continue
        if _within_first_five_listed_bars(series, index, instrument):
            continue
        name = _stock_name(instrument, symbol)
        trade_date = cn_market_date_from_ms(series.timestamp[index])
        if trade_date is None:
            continue
        reference = _reference_close(series, index)
        if reference <= 0:
            continue
        rate = price_limit_rate(symbol, name, trade_date)
        upper = daily_limit_price(reference, rate, direction="up")
        lower = daily_limit_price(reference, rate, direction="down")
        touched_up = _at_or_above(series.high[index], upper)
        closed_up = touched_up and _closed_up(series, index, upper)
        touched_down = _at_or_below(series.low[index], lower)
        closed_down = touched_down and _closed_down(series, index, lower)
        one_price_up = closed_up and _at_or_above(series.low[index], upper)
        one_price_down = closed_down and _at_or_below(series.high[index], lower)

        prior_up_streak = 0
        cursor = index - 1
        while cursor >= 1:
            prior_date = cn_market_date_from_ms(series.timestamp[cursor])
            if prior_date is None:
                break
            prior_reference = _reference_close(series, cursor)
            prior_upper = daily_limit_price(
                prior_reference, price_limit_rate(symbol, name, prior_date), direction="up"
            )
            if not _closed_up(series, cursor, prior_upper):
                break
            prior_up_streak += 1
            cursor -= 1

        floor_to_ceiling = touched_down and _at_or_above(series.close[index], upper)
        ceiling_to_floor = touched_up and _at_or_below(series.close[index], lower)
        if touched_up:
            counts["limit_up_touches"] += 1
            if closed_up:
                counts["closed_limit_up"] += 1
                if prior_up_streak == 0:
                    counts["first_board_closed"] += 1
                if one_price_up:
                    counts["one_price_limit_up"] += 1
                    signal_type = "一字涨停"
                    action = "成交约束：通常无法排入，不作为买入候选"
                else:
                    signal_type = "首板封住" if prior_up_streak == 0 else f"{prior_up_streak + 1}板封住"
                    action = "后验观察：等待分钟级封板质量验证，不作为当日追板指令"
            else:
                counts["broken_boards"] += 1
                signal_type = "炸板"
                action = "风险观察：不追，次日关注承接与主题扩散"
            if ceiling_to_floor:
                counts["ceiling_to_floor"] += 1
                signal_type = "天地板"
                action = "极端风险：排除交易候选"
            if not floor_to_ceiling:
                signals.append(
                    PriceLimitSignal(
                        symbol=symbol,
                        name=name,
                        signal_type=signal_type,
                        action=action,
                        close=series.close[index],
                        board_rate=rate,
                        prior_streak=prior_up_streak,
                        verdict=_verdict(signal_type),
                        themes=symbol_themes.get(symbol, []),
                        notes=["收盘状态后验确认", "日K不含封单和排队位置"],
                    )
                )

        if touched_down:
            counts["limit_down_touches"] += 1
            if closed_down:
                counts["closed_limit_down"] += 1
                if one_price_down:
                    counts["one_price_limit_down"] += 1
                    signal_type = "一字跌停"
                    action = "极端流动性风险：不抄底，已有退出可能无法成交"
                else:
                    signal_type = "收盘封跌停"
                    action = "风险观察：不抄底，已有退出可能顺延"
            else:
                counts["broken_floors"] += 1
                signal_type = "跌停打开"
                action = "后验观察：等待分钟级收复质量验证，不作为当日抄底指令"
            extreme_path = floor_to_ceiling
            if extreme_path:
                counts["floor_to_ceiling"] += 1
                signal_type = "地天板"
                action = "极端反转观察：不追，次日验证承接"
            if not ceiling_to_floor:
                signals.append(
                    PriceLimitSignal(
                        symbol=symbol,
                        name=name,
                        signal_type=signal_type,
                        action=action,
                        close=series.close[index],
                        board_rate=rate,
                        prior_streak=0,
                        verdict=_verdict(signal_type),
                        themes=symbol_themes.get(symbol, []),
                        notes=["收盘状态后验确认", "日K不含盘中开板时间"],
                    )
                )

    priority = {
        "天地板": 0,
        "地天板": 1,
        "一字跌停": 2,
        "收盘封跌停": 3,
        "炸板": 4,
        "跌停打开": 5,
        "一字涨停": 6,
        "首板封住": 7,
    }
    signals.sort(
        key=lambda item: (
            priority.get(item.signal_type, 4 if "板封住" in item.signal_type else 9),
            -item.prior_streak,
            item.symbol,
        )
    )
    notes = [
        "结论使用收盘确认后、下一交易日开盘可成交的样本外回测，不偷用涨停价或跌停价成交。",
        "当前所有可执行变体样本外期望均为负，追板与抄底通道保持关闭。",
        "若要重开通道，需分钟线影子盘同时通过成交率、封单质量、期望收益和尾部回撤门槛。",
    ]
    return PriceLimitWatchReport(
        as_of=as_of,
        ceiling_verdict="关闭追板通道",
        ceiling_reason="首板、主线首板和高位连板确认后次日开盘买入，样本外5日均值全部为负",
        floor_verdict="关闭抄底通道",
        floor_reason="跌停打开、主线跌停打开和封跌停确认后次日开盘买入，样本外5日均值全部为负",
        evidence_as_of=EXECUTABLE_EVIDENCE_AS_OF,
        backtest_cases=EXECUTABLE_BACKTEST_CASES,
        reopen_conditions=[
            "分钟线/逐笔影子盘按真实排队与成交概率记录，样本外实际成交不少于200笔",
            "扣除费用后信号后5日均值大于0，且均值95%置信区间下沿大于0",
            "5%尾部收益优于-10%，平均5日路径回撤优于-6%",
            "至少连续60个交易日影子盘未失效，再允许小仓试错；未同时满足则继续关闭",
        ],
        signals=signals[:signal_limit],
        notes=notes,
        **counts,
    )
