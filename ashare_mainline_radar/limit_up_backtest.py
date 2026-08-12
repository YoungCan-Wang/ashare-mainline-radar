from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import floor, sqrt
from statistics import mean, median, stdev
from typing import Any

from .config import theme_symbol_map
from .execution import TradingCostModel, daily_limit_price, price_limit_rate
from .market import build_theme_snapshots, compute_symbol_snapshot
from .models import KlineSeries, cn_market_date_from_ms


@dataclass(frozen=True)
class LimitUpEvent:
    symbol: str
    name: str
    signal_date: str
    board_rate: float
    prior_board_streak: int
    themes: list[str]
    prior_mainline_themes: list[str]
    prior_breadth_regime: str
    closed_limit_up: bool
    one_price_limit_up: bool
    broken_board: bool
    ceiling_to_floor: bool
    floor_to_ceiling: bool
    amount_ratio_20d: float | None
    entry_price: float
    returns: dict[str, float | None]
    exit_delay_days: dict[str, int]
    next_day_limit_down: bool
    worst_5d_drawdown: float | None
    confirmed_entry_price: float | None
    confirmed_entry_gap: float | None
    confirmed_entry_blocked_reason: str | None
    confirmed_returns: dict[str, float | None]
    confirmed_exit_delay_days: dict[str, int]
    confirmed_worst_5d_drawdown: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LimitDownEvent:
    symbol: str
    name: str
    signal_date: str
    board_rate: float
    prior_down_streak: int
    themes: list[str]
    prior_mainline_themes: list[str]
    prior_breadth_regime: str
    closed_limit_down: bool
    one_price_limit_down: bool
    broken_floor: bool
    floor_to_ceiling: bool
    amount_ratio_20d: float | None
    entry_price: float
    returns: dict[str, float | None]
    exit_delay_days: dict[str, int]
    next_day_limit_down: bool
    worst_5d_drawdown: float | None
    best_5d_runup: float | None
    confirmed_entry_price: float | None
    confirmed_entry_gap: float | None
    confirmed_entry_blocked_reason: str | None
    confirmed_returns: dict[str, float | None]
    confirmed_exit_delay_days: dict[str, int]
    confirmed_worst_5d_drawdown: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bar(series: KlineSeries, index: int) -> dict[str, float] | None:
    fields = (series.open, series.high, series.low, series.close, series.volume, series.amount)
    if index < 0 or any(index >= len(field) for field in fields):
        return None
    return {
        "open": series.open[index],
        "high": series.high[index],
        "low": series.low[index],
        "close": series.close[index],
        "volume": series.volume[index],
        "amount": series.amount[index],
    }


def _at_price(value: float, target: float) -> bool:
    return value >= target - 0.005


def _at_floor(value: float, target: float) -> bool:
    return value <= target + 0.005


def _stock_name(instrument: dict[str, Any] | None, symbol: str) -> str:
    instrument = instrument or {}
    return str(instrument.get("name") or instrument.get("display_name") or symbol)


def _listing_date(instrument: dict[str, Any] | None) -> str | None:
    ext = (instrument or {}).get("ext")
    if not isinstance(ext, dict):
        return None
    value = ext.get("listing_date")
    return str(value) if value else None


def _is_stock(symbol: str, instrument: dict[str, Any] | None) -> bool:
    if not symbol.endswith((".SH", ".SZ", ".BJ")):
        return False
    name = _stock_name(instrument, symbol).upper()
    return not any(token in name for token in ("ETF", "LOF", "REIT", "指数", "基金", "转债", "退"))


def _is_known_st(name: str) -> bool:
    upper = name.upper().replace(" ", "")
    return upper.startswith(("ST", "*ST"))


def _within_first_five_listed_bars(series: KlineSeries, index: int, listing_date: str | None) -> bool:
    if not listing_date or not series.timestamp:
        return False
    first_date = cn_market_date_from_ms(series.timestamp[0])
    if first_date is None or listing_date < first_date:
        return False
    listed_indices = [
        cursor
        for cursor, timestamp in enumerate(series.timestamp[: index + 1])
        if (cn_market_date_from_ms(timestamp) or "") >= listing_date
    ]
    return index in listed_indices[:5]


def _amount_ratio(series: KlineSeries, index: int) -> float | None:
    if index < 20:
        return None
    baseline = [value for value in series.amount[index - 20 : index] if value > 0]
    if not baseline:
        return None
    average = mean(baseline)
    return series.amount[index] / average if average > 0 else None


def _net_return(
    entry_price: float,
    exit_price: float,
    entry_date: str,
    exit_date: str,
    cost_model: TradingCostModel,
    position_notional: float,
) -> float:
    buy = cost_model.fee_breakdown(position_notional, entry_date, side="buy")
    exit_notional = position_notional * exit_price / entry_price
    sell = cost_model.fee_breakdown(exit_notional, exit_date, side="sell")
    buy_fee_rate = buy.total / position_notional
    sell_fee_rate = sell.total / exit_notional
    slipped_exit = exit_price * (1 - cost_model.slippage_rate)
    return slipped_exit * (1 - sell_fee_rate) / (entry_price * (1 + buy_fee_rate)) - 1


def _sealed_limit_down(series: KlineSeries, index: int, symbol: str, name: str) -> bool:
    bar = _bar(series, index)
    previous = _bar(series, index - 1)
    trade_date = cn_market_date_from_ms(series.timestamp[index]) if index < len(series.timestamp) else None
    if bar is None or previous is None or trade_date is None or bar["volume"] <= 0:
        return False
    reference = series.prev_close[index] if index < len(series.prev_close) and series.prev_close[index] > 0 else previous["close"]
    limit_price = daily_limit_price(reference, price_limit_rate(symbol, name, trade_date), direction="down")
    return _at_floor(bar["high"], limit_price) and _at_floor(bar["close"], limit_price)


def _confirmed_next_open_path(
    series: KlineSeries,
    calendar: list[int],
    calendar_index: int,
    lookup: dict[int, int],
    symbol: str,
    name: str,
    signal_close: float,
    cost_model: TradingCostModel,
    position_fraction: float,
) -> tuple[
    float | None,
    float | None,
    str | None,
    dict[str, float | None],
    dict[str, int],
    float | None,
]:
    """Model an executable entry after the closing state is known.

    Entry is the next session open.  An opening price already locked at the
    upper limit is rejected because a day bar cannot prove queue access.
    Returns use the first sellable close from T+1 onward.
    """

    returns = {"day2_close": None, "day3_close": None, "day5_close": None}
    delays = {label: 0 for label in returns}
    if calendar_index + 1 >= len(calendar):
        return None, None, "missing_next_session", returns, delays, None
    entry_index = lookup.get(calendar[calendar_index + 1])
    entry_bar = _bar(series, entry_index) if entry_index is not None else None
    if entry_index is None or entry_bar is None or entry_bar["volume"] <= 0 or entry_bar["open"] <= 0:
        return None, None, "next_session_suspended_or_missing", returns, delays, None
    entry_date = cn_market_date_from_ms(series.timestamp[entry_index])
    previous = _bar(series, entry_index - 1)
    if entry_date is None or previous is None or previous["close"] <= 0:
        return None, None, "missing_entry_reference", returns, delays, None
    reference = (
        series.prev_close[entry_index]
        if entry_index < len(series.prev_close) and series.prev_close[entry_index] > 0
        else previous["close"]
    )
    entry_upper = daily_limit_price(
        reference, price_limit_rate(symbol, name, entry_date), direction="up"
    )
    if _at_price(entry_bar["open"], entry_upper):
        return None, None, "next_open_at_limit_up", returns, delays, None

    entry_price = entry_bar["open"]
    entry_gap = entry_price / signal_close - 1 if signal_close > 0 else None
    for label, offset in {"day2_close": 2, "day3_close": 3, "day5_close": 5}.items():
        if calendar_index + offset >= len(calendar):
            continue
        target_index = lookup.get(calendar[calendar_index + offset])
        if target_index is None:
            continue
        resolved, exit_price, delay = _sellable_exit(
            series, target_index, symbol, name, "close"
        )
        delays[label] = delay
        if resolved is None or exit_price is None:
            continue
        exit_date = cn_market_date_from_ms(series.timestamp[resolved]) or entry_date
        returns[label] = _net_return(
            entry_price,
            exit_price,
            entry_date,
            exit_date,
            cost_model,
            cost_model.account_capital * position_fraction,
        )

    path_lows = [
        series.low[path_index]
        for offset in range(1, 6)
        if calendar_index + offset < len(calendar)
        for path_index in [lookup.get(calendar[calendar_index + offset])]
        if path_index is not None and series.low[path_index] > 0
    ]
    worst_drawdown = min(path_lows) / entry_price - 1 if path_lows else None
    return entry_price, entry_gap, None, returns, delays, worst_drawdown


def _sellable_exit(
    series: KlineSeries,
    target_index: int,
    symbol: str,
    name: str,
    field: str,
) -> tuple[int | None, float | None, int]:
    cursor = target_index
    while cursor < len(series.close):
        bar = _bar(series, cursor)
        if bar is None:
            return None, None, cursor - target_index
        if bar["volume"] <= 0 or _sealed_limit_down(series, cursor, symbol, name):
            cursor += 1
            continue
        value = bar[field]
        return cursor, value if value > 0 else None, cursor - target_index
    return None, None, cursor - target_index


def _calendar(klines: dict[str, KlineSeries]) -> list[int]:
    counts: dict[int, int] = {}
    for series in klines.values():
        for timestamp in series.timestamp:
            counts[timestamp] = counts.get(timestamp, 0) + 1
    if not counts:
        return []
    minimum_coverage = max(1, floor(len(klines) * 0.35))
    return sorted(timestamp for timestamp, count in counts.items() if count >= minimum_coverage)


def _index_by_timestamp(series: KlineSeries) -> dict[int, int]:
    return {timestamp: index for index, timestamp in enumerate(series.timestamp)}


def _prior_breadth_by_date(
    klines: dict[str, KlineSeries],
    calendar: list[int],
) -> dict[int, str]:
    changes: dict[int, list[float]] = {timestamp: [] for timestamp in calendar}
    calendar_set = set(calendar)
    for series in klines.values():
        for index in range(1, len(series.close)):
            timestamp = series.timestamp[index]
            previous = series.close[index - 1]
            if timestamp not in calendar_set or previous <= 0:
                continue
            changes[timestamp].append(series.close[index] / previous - 1)
    regimes: dict[int, str] = {}
    for timestamp, values in changes.items():
        advance = sum(value > 0 for value in values) / len(values) if values else 0.0
        regimes[timestamp] = "strong" if advance >= 0.55 else "weak" if advance < 0.35 else "neutral"
    return regimes


def _prior_mainlines_by_date(
    theme_config: dict[str, Any],
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    calendar: list[int],
    warmup_days: int,
) -> dict[int, set[str]]:
    symbol_themes = theme_symbol_map(theme_config)
    configured = set(symbol_themes)
    lookups = {symbol: _index_by_timestamp(series) for symbol, series in klines.items() if symbol in configured}
    result: dict[int, set[str]] = {}
    for calendar_index in range(max(20, warmup_days - 1), len(calendar)):
        timestamp = calendar[calendar_index]
        snapshots = {}
        for symbol, lookup in lookups.items():
            index = lookup.get(timestamp)
            series = klines[symbol]
            if index is None or index < 20:
                continue
            clipped = KlineSeries(
                symbol=symbol,
                timestamp=series.timestamp[: index + 1],
                open=series.open[: index + 1],
                high=series.high[: index + 1],
                low=series.low[: index + 1],
                close=series.close[: index + 1],
                volume=series.volume[: index + 1],
                amount=series.amount[: index + 1],
                prev_close=series.prev_close[: index + 1],
            )
            snapshot = compute_symbol_snapshot(
                symbol, clipped, instruments.get(symbol), symbol_themes.get(symbol, [])
            )
            if snapshot is not None:
                snapshots[symbol] = snapshot
        themes = build_theme_snapshots(theme_config, snapshots)
        result[timestamp] = {
            item.name for item in themes[:3] if item.status in {"主线成立", "主线候选"}
        }
    return result


def prepare_limit_event_context(
    theme_config: dict[str, Any],
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    warmup_days: int,
) -> tuple[list[int], dict[int, str], dict[int, set[str]]]:
    """Precompute the shared point-in-time market context for ceiling and floor studies."""
    calendar = _calendar(klines)
    return (
        calendar,
        _prior_breadth_by_date(klines, calendar),
        _prior_mainlines_by_date(theme_config, klines, instruments, calendar, warmup_days),
    )


def collect_limit_up_events(
    theme_config: dict[str, Any],
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    *,
    warmup_days: int = 80,
    cost_model: TradingCostModel | None = None,
    position_fraction: float = 0.03,
    event_context: tuple[list[int], dict[int, str], dict[int, set[str]]] | None = None,
) -> tuple[list[LimitUpEvent], dict[str, Any]]:
    cost_model = cost_model or TradingCostModel()
    calendar, breadth, mainlines = event_context or prepare_limit_event_context(
        theme_config, klines, instruments, warmup_days
    )
    timestamp_position = {timestamp: index for index, timestamp in enumerate(calendar)}
    symbol_themes = theme_symbol_map(theme_config)
    events: list[LimitUpEvent] = []
    excluded_current_st = 0
    excluded_ipo_days = 0
    observed_limit_touches = 0

    for symbol, series in klines.items():
        instrument = instruments.get(symbol)
        name = _stock_name(instrument, symbol)
        if not _is_stock(symbol, instrument):
            continue
        if _is_known_st(name):
            excluded_current_st += 1
            continue
        listing_date = _listing_date(instrument)
        board_streak = 0
        for index in range(1, len(series.close)):
            timestamp = series.timestamp[index]
            calendar_index = timestamp_position.get(timestamp)
            trade_date = cn_market_date_from_ms(timestamp)
            bar = _bar(series, index)
            previous = _bar(series, index - 1)
            if trade_date is None or bar is None or previous is None or previous["close"] <= 0:
                board_streak = 0
                continue
            rate = price_limit_rate(symbol, name, trade_date)
            reference = (
                series.prev_close[index]
                if index < len(series.prev_close) and series.prev_close[index] > 0
                else previous["close"]
            )
            upper = daily_limit_price(reference, rate, direction="up")
            lower = daily_limit_price(reference, rate, direction="down")
            touched_up = bar["volume"] > 0 and _at_price(bar["high"], upper)
            closed_up = touched_up and _at_price(bar["close"], upper)
            prior_streak = board_streak
            board_streak = prior_streak + 1 if closed_up else 0
            if not touched_up:
                continue
            observed_limit_touches += 1
            if _within_first_five_listed_bars(series, index, listing_date):
                excluded_ipo_days += 1
                continue
            if calendar_index is None or calendar_index < warmup_days or calendar_index + 5 >= len(calendar):
                continue

            one_price = (
                _at_price(bar["open"], upper)
                and _at_price(bar["low"], upper)
                and _at_price(bar["close"], upper)
            )
            previous_timestamp = calendar[calendar_index - 1]
            previous_mainlines = mainlines.get(previous_timestamp, set())
            mapped_themes = symbol_themes.get(symbol, [])
            aligned = sorted(set(mapped_themes) & previous_mainlines)
            entry_price = upper
            returns: dict[str, float | None] = {}
            delays: dict[str, int] = {}
            lookup = _index_by_timestamp(series)
            horizons = {
                "next_open": (1, "open"),
                "next_close": (1, "close"),
                "day3_close": (3, "close"),
                "day5_close": (5, "close"),
            }
            for label, (offset, field) in horizons.items():
                target_timestamp = calendar[calendar_index + offset]
                target_index = lookup.get(target_timestamp)
                if target_index is None:
                    returns[label] = None
                    delays[label] = 0
                    continue
                resolved, exit_price, delay = _sellable_exit(series, target_index, symbol, name, field)
                delays[label] = delay
                if resolved is None or exit_price is None:
                    returns[label] = None
                    continue
                exit_date = cn_market_date_from_ms(series.timestamp[resolved]) or trade_date
                returns[label] = _net_return(
                    entry_price,
                    exit_price,
                    trade_date,
                    exit_date,
                    cost_model,
                    cost_model.account_capital * position_fraction,
                )

            path_lows: list[float] = []
            for offset in range(0, 6):
                idx = lookup.get(calendar[calendar_index + offset])
                if idx is not None and series.low[idx] > 0:
                    path_lows.append(series.low[idx])
            worst_drawdown = min(path_lows) / entry_price - 1 if path_lows else None
            next_index = lookup.get(calendar[calendar_index + 1])
            next_limit_down = bool(
                next_index is not None and _sealed_limit_down(series, next_index, symbol, name)
            )
            (
                confirmed_entry_price,
                confirmed_entry_gap,
                confirmed_entry_blocked_reason,
                confirmed_returns,
                confirmed_delays,
                confirmed_worst_drawdown,
            ) = _confirmed_next_open_path(
                series,
                calendar,
                calendar_index,
                lookup,
                symbol,
                name,
                bar["close"],
                cost_model,
                position_fraction,
            )
            events.append(
                LimitUpEvent(
                    symbol=symbol,
                    name=name,
                    signal_date=trade_date,
                    board_rate=rate,
                    prior_board_streak=prior_streak,
                    themes=list(mapped_themes),
                    prior_mainline_themes=aligned,
                    prior_breadth_regime=breadth.get(previous_timestamp, "unknown"),
                    closed_limit_up=closed_up,
                    one_price_limit_up=one_price,
                    broken_board=not closed_up,
                    ceiling_to_floor=_at_price(bar["high"], upper) and _at_floor(bar["close"], lower),
                    floor_to_ceiling=_at_floor(bar["low"], lower) and _at_price(bar["close"], upper),
                    amount_ratio_20d=_amount_ratio(series, index),
                    entry_price=entry_price,
                    returns=returns,
                    exit_delay_days=delays,
                    next_day_limit_down=next_limit_down,
                    worst_5d_drawdown=worst_drawdown,
                    confirmed_entry_price=confirmed_entry_price,
                    confirmed_entry_gap=confirmed_entry_gap,
                    confirmed_entry_blocked_reason=confirmed_entry_blocked_reason,
                    confirmed_returns=confirmed_returns,
                    confirmed_exit_delay_days=confirmed_delays,
                    confirmed_worst_5d_drawdown=confirmed_worst_drawdown,
                )
            )

    metadata = {
        "calendar_start": cn_market_date_from_ms(calendar[warmup_days]) if len(calendar) > warmup_days else None,
        "calendar_end": cn_market_date_from_ms(calendar[-1]) if calendar else None,
        "calendar_days": max(0, len(calendar) - warmup_days),
        "symbols_with_klines": len(klines),
        "observed_limit_touches": observed_limit_touches,
        "usable_events": len(events),
        "excluded_current_st_symbols": excluded_current_st,
        "excluded_ipo_first_five_day_touches": excluded_ipo_days,
    }
    return events, metadata


def collect_limit_down_events(
    theme_config: dict[str, Any],
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    *,
    warmup_days: int = 80,
    cost_model: TradingCostModel | None = None,
    position_fraction: float = 0.03,
    event_context: tuple[list[int], dict[int, str], dict[int, set[str]]] | None = None,
) -> tuple[list[LimitDownEvent], dict[str, Any]]:
    """Build a separate event study for buying at the daily lower price limit.

    A daily low at the limit does not prove a realistic queue fill, so the
    touch-at-floor result is deliberately labelled as a naive baseline.  Any
    variant conditioned on the closing state is also marked as conditional.
    """

    cost_model = cost_model or TradingCostModel()
    calendar, breadth, mainlines = event_context or prepare_limit_event_context(
        theme_config, klines, instruments, warmup_days
    )
    timestamp_position = {timestamp: index for index, timestamp in enumerate(calendar)}
    symbol_themes = theme_symbol_map(theme_config)
    events: list[LimitDownEvent] = []
    excluded_current_st = 0
    excluded_ipo_days = 0
    observed_limit_down_touches = 0

    for symbol, series in klines.items():
        instrument = instruments.get(symbol)
        name = _stock_name(instrument, symbol)
        if not _is_stock(symbol, instrument):
            continue
        if _is_known_st(name):
            excluded_current_st += 1
            continue
        listing_date = _listing_date(instrument)
        down_streak = 0
        lookup = _index_by_timestamp(series)
        for index in range(1, len(series.close)):
            timestamp = series.timestamp[index]
            calendar_index = timestamp_position.get(timestamp)
            trade_date = cn_market_date_from_ms(timestamp)
            bar = _bar(series, index)
            previous = _bar(series, index - 1)
            if trade_date is None or bar is None or previous is None or previous["close"] <= 0:
                down_streak = 0
                continue
            rate = price_limit_rate(symbol, name, trade_date)
            reference = (
                series.prev_close[index]
                if index < len(series.prev_close) and series.prev_close[index] > 0
                else previous["close"]
            )
            lower = daily_limit_price(reference, rate, direction="down")
            upper = daily_limit_price(reference, rate, direction="up")
            touched_down = bar["volume"] > 0 and _at_floor(bar["low"], lower)
            closed_down = touched_down and _at_floor(bar["close"], lower)
            prior_streak = down_streak
            down_streak = prior_streak + 1 if closed_down else 0
            if not touched_down:
                continue
            observed_limit_down_touches += 1
            if _within_first_five_listed_bars(series, index, listing_date):
                excluded_ipo_days += 1
                continue
            if calendar_index is None or calendar_index < warmup_days or calendar_index + 5 >= len(calendar):
                continue

            one_price = (
                _at_floor(bar["open"], lower)
                and _at_floor(bar["high"], lower)
                and _at_floor(bar["close"], lower)
            )
            previous_timestamp = calendar[calendar_index - 1]
            previous_mainlines = mainlines.get(previous_timestamp, set())
            mapped_themes = symbol_themes.get(symbol, [])
            aligned = sorted(set(mapped_themes) & previous_mainlines)
            returns: dict[str, float | None] = {}
            delays: dict[str, int] = {}
            for label, (offset, field) in {
                "next_open": (1, "open"),
                "next_close": (1, "close"),
                "day3_close": (3, "close"),
                "day5_close": (5, "close"),
            }.items():
                target_index = lookup.get(calendar[calendar_index + offset])
                if target_index is None:
                    returns[label] = None
                    delays[label] = 0
                    continue
                resolved, exit_price, delay = _sellable_exit(series, target_index, symbol, name, field)
                delays[label] = delay
                if resolved is None or exit_price is None:
                    returns[label] = None
                    continue
                exit_date = cn_market_date_from_ms(series.timestamp[resolved]) or trade_date
                returns[label] = _net_return(
                    lower,
                    exit_price,
                    trade_date,
                    exit_date,
                    cost_model,
                    cost_model.account_capital * position_fraction,
                )

            path_lows: list[float] = []
            path_highs: list[float] = []
            for offset in range(0, 6):
                path_index = lookup.get(calendar[calendar_index + offset])
                if path_index is None:
                    continue
                if series.low[path_index] > 0:
                    path_lows.append(series.low[path_index])
                if series.high[path_index] > 0:
                    path_highs.append(series.high[path_index])
            next_index = lookup.get(calendar[calendar_index + 1])
            (
                confirmed_entry_price,
                confirmed_entry_gap,
                confirmed_entry_blocked_reason,
                confirmed_returns,
                confirmed_delays,
                confirmed_worst_drawdown,
            ) = _confirmed_next_open_path(
                series,
                calendar,
                calendar_index,
                lookup,
                symbol,
                name,
                bar["close"],
                cost_model,
                position_fraction,
            )
            events.append(
                LimitDownEvent(
                    symbol=symbol,
                    name=name,
                    signal_date=trade_date,
                    board_rate=rate,
                    prior_down_streak=prior_streak,
                    themes=list(mapped_themes),
                    prior_mainline_themes=aligned,
                    prior_breadth_regime=breadth.get(previous_timestamp, "unknown"),
                    closed_limit_down=closed_down,
                    one_price_limit_down=one_price,
                    broken_floor=not closed_down,
                    floor_to_ceiling=_at_floor(bar["low"], lower) and _at_price(bar["close"], upper),
                    amount_ratio_20d=_amount_ratio(series, index),
                    entry_price=lower,
                    returns=returns,
                    exit_delay_days=delays,
                    next_day_limit_down=bool(
                        next_index is not None and _sealed_limit_down(series, next_index, symbol, name)
                    ),
                    worst_5d_drawdown=min(path_lows) / lower - 1 if path_lows else None,
                    best_5d_runup=max(path_highs) / lower - 1 if path_highs else None,
                    confirmed_entry_price=confirmed_entry_price,
                    confirmed_entry_gap=confirmed_entry_gap,
                    confirmed_entry_blocked_reason=confirmed_entry_blocked_reason,
                    confirmed_returns=confirmed_returns,
                    confirmed_exit_delay_days=confirmed_delays,
                    confirmed_worst_5d_drawdown=confirmed_worst_drawdown,
                )
            )

    return events, {
        "observed_limit_down_touches": observed_limit_down_touches,
        "usable_limit_down_events": len(events),
        "excluded_current_st_symbols": excluded_current_st,
        "excluded_ipo_first_five_day_limit_down_touches": excluded_ipo_days,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = floor(position)
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _event_metrics(events: list[LimitUpEvent]) -> dict[str, Any]:
    horizon_metrics: dict[str, Any] = {}
    for label in ("next_open", "next_close", "day3_close", "day5_close"):
        values = [float(event.returns[label]) for event in events if event.returns.get(label) is not None]
        average = mean(values) if values else None
        standard_error = stdev(values) / sqrt(len(values)) if len(values) >= 2 else None
        horizon_metrics[label] = {
            "trades": len(values),
            "win_rate": sum(value > 0 for value in values) / len(values) if values else None,
            "average_return": average,
            "median_return": median(values) if values else None,
            "p05_return": _percentile(values, 0.05),
            "p95_return": _percentile(values, 0.95),
            "worst_return": min(values) if values else None,
            "mean_ci95_low": average - 1.96 * standard_error if standard_error is not None else None,
            "mean_ci95_high": average + 1.96 * standard_error if standard_error is not None else None,
        }
    drawdowns = [event.worst_5d_drawdown for event in events if event.worst_5d_drawdown is not None]
    return {
        "signals": len(events),
        "horizons": horizon_metrics,
        "next_day_limit_down_rate": (
            sum(event.next_day_limit_down for event in events) / len(events) if events else None
        ),
        "exit_delayed_rate": (
            sum(any(delay > 0 for delay in event.exit_delay_days.values()) for event in events) / len(events)
            if events
            else None
        ),
        "average_worst_5d_drawdown": mean(drawdowns) if drawdowns else None,
        "p05_worst_5d_drawdown": _percentile(drawdowns, 0.05),
    }


def _confirmed_event_metrics(events: list[LimitUpEvent | LimitDownEvent]) -> dict[str, Any]:
    executable = [event for event in events if event.confirmed_entry_price is not None]
    horizon_metrics: dict[str, Any] = {}
    for label in ("day2_close", "day3_close", "day5_close"):
        values = [
            float(event.confirmed_returns[label])
            for event in executable
            if event.confirmed_returns.get(label) is not None
        ]
        average = mean(values) if values else None
        standard_error = stdev(values) / sqrt(len(values)) if len(values) >= 2 else None
        horizon_metrics[label] = {
            "trades": len(values),
            "win_rate": sum(value > 0 for value in values) / len(values) if values else None,
            "average_return": average,
            "median_return": median(values) if values else None,
            "p05_return": _percentile(values, 0.05),
            "p95_return": _percentile(values, 0.95),
            "worst_return": min(values) if values else None,
            "mean_ci95_low": average - 1.96 * standard_error if standard_error is not None else None,
            "mean_ci95_high": average + 1.96 * standard_error if standard_error is not None else None,
        }
    gaps = [event.confirmed_entry_gap for event in executable if event.confirmed_entry_gap is not None]
    drawdowns = [
        event.confirmed_worst_5d_drawdown
        for event in executable
        if event.confirmed_worst_5d_drawdown is not None
    ]
    return {
        "signals": len(events),
        "executable_entries": len(executable),
        "blocked_entry_rate": 1 - len(executable) / len(events) if events else None,
        "average_entry_gap": mean(gaps) if gaps else None,
        "horizons": horizon_metrics,
        "exit_delayed_rate": (
            sum(
                any(delay > 0 for delay in event.confirmed_exit_delay_days.values())
                for event in executable
            )
            / len(executable)
            if executable
            else None
        ),
        "average_worst_5d_drawdown": mean(drawdowns) if drawdowns else None,
        "p05_worst_5d_drawdown": _percentile(drawdowns, 0.05),
    }


def build_limit_up_backtest_report(
    events: list[LimitUpEvent],
    metadata: dict[str, Any],
    limit_down_events: list[LimitDownEvent] | None = None,
) -> dict[str, Any]:
    limit_down_events = limit_down_events or []
    ordered_dates = sorted(
        {event.signal_date for event in events} | {event.signal_date for event in limit_down_events}
    )
    split_60 = ordered_dates[floor(len(ordered_dates) * 0.60)] if ordered_dates else ""
    split_80 = ordered_dates[floor(len(ordered_dates) * 0.80)] if ordered_dates else ""

    variants = {
        "touch_fill_naive_baseline": events,
        "close_sealed_non_one_price_conditional": [
            event for event in events if event.closed_limit_up and not event.one_price_limit_up
        ],
        "first_board_close_sealed_conditional": [
            event
            for event in events
            if event.closed_limit_up and not event.one_price_limit_up and event.prior_board_streak == 0
        ],
        "mainboard_first_board_close_sealed_conditional": [
            event
            for event in events
            if event.board_rate == 0.10
            and event.closed_limit_up
            and not event.one_price_limit_up
            and event.prior_board_streak == 0
        ],
        "growth_board_first_board_close_sealed_conditional": [
            event
            for event in events
            if event.board_rate == 0.20
            and event.closed_limit_up
            and not event.one_price_limit_up
            and event.prior_board_streak == 0
        ],
        "mainline_first_board_close_sealed_conditional": [
            event
            for event in events
            if event.closed_limit_up
            and not event.one_price_limit_up
            and event.prior_board_streak == 0
            and event.prior_mainline_themes
        ],
        "mainline_first_board_strong_tape_conditional": [
            event
            for event in events
            if event.closed_limit_up
            and not event.one_price_limit_up
            and event.prior_board_streak == 0
            and event.prior_mainline_themes
            and event.prior_breadth_regime == "strong"
        ],
        "mainline_first_board_neutral_tape_conditional": [
            event
            for event in events
            if event.closed_limit_up
            and not event.one_price_limit_up
            and event.prior_board_streak == 0
            and event.prior_mainline_themes
            and event.prior_breadth_regime == "neutral"
        ],
        "mainline_first_board_weak_tape_conditional": [
            event
            for event in events
            if event.closed_limit_up
            and not event.one_price_limit_up
            and event.prior_board_streak == 0
            and event.prior_mainline_themes
            and event.prior_breadth_regime == "weak"
        ],
        "broken_board_touch": [event for event in events if event.broken_board],
        "high_board_close_sealed_conditional": [
            event
            for event in events
            if event.closed_limit_up and not event.one_price_limit_up and event.prior_board_streak >= 2
        ],
    }
    periods = {
        "train": lambda event: event.signal_date <= split_60,
        "validation": lambda event: split_60 < event.signal_date <= split_80,
        "test": lambda event: event.signal_date > split_80,
    }
    variant_metrics = {}
    for name, selected in variants.items():
        variant_metrics[name] = {
            "all": _event_metrics(selected),
            **{
                period: _event_metrics([event for event in selected if predicate(event)])
                for period, predicate in periods.items()
            },
        }

    mainline_first_boards = variants["mainline_first_board_close_sealed_conditional"]
    mainline_yearly = {
        year: _event_metrics([event for event in mainline_first_boards if event.signal_date[:4] == year])
        for year in sorted({event.signal_date[:4] for event in mainline_first_boards})
    }
    test_mainline_events = [event for event in mainline_first_boards if periods["test"](event)]
    test_theme_counts: dict[str, int] = {}
    for event in test_mainline_events:
        for theme in event.prior_mainline_themes:
            test_theme_counts[theme] = test_theme_counts.get(theme, 0) + 1

    path_events = {
        "ceiling_to_floor": [event for event in events if event.ceiling_to_floor],
        "floor_to_ceiling": [event for event in events if event.floor_to_ceiling],
        "one_price_limit_up": [event for event in events if event.one_price_limit_up],
        "next_day_limit_down": [event for event in events if event.next_day_limit_down],
    }
    floor_variants = {
        "limit_down_touch_buy_naive_baseline": limit_down_events,
        "close_limit_down_buy_conditional": [
            event for event in limit_down_events if event.closed_limit_down
        ],
        "broken_floor_rebound_conditional": [
            event for event in limit_down_events if event.broken_floor
        ],
        "mainline_broken_floor_rebound_conditional": [
            event
            for event in limit_down_events
            if event.broken_floor and event.prior_mainline_themes
        ],
        "one_price_limit_down_buy": [
            event for event in limit_down_events if event.one_price_limit_down
        ],
        "consecutive_limit_down_buy": [
            event for event in limit_down_events if event.prior_down_streak >= 1
        ],
    }
    floor_variant_metrics = {
        name: {
            "all": _event_metrics(selected),
            **{
                period: _event_metrics([event for event in selected if predicate(event)])
                for period, predicate in periods.items()
            },
        }
        for name, selected in floor_variants.items()
    }
    executable_variants = {
        "chase_first_board_next_open": variants["first_board_close_sealed_conditional"],
        "chase_mainline_first_board_next_open": variants[
            "mainline_first_board_close_sealed_conditional"
        ],
        "chase_high_board_next_open": variants["high_board_close_sealed_conditional"],
        "buy_broken_floor_next_open": floor_variants["broken_floor_rebound_conditional"],
        "buy_mainline_broken_floor_next_open": floor_variants[
            "mainline_broken_floor_rebound_conditional"
        ],
        "buy_close_limit_down_next_open": floor_variants[
            "close_limit_down_buy_conditional"
        ],
    }
    executable_variant_metrics = {
        name: {
            "all": _confirmed_event_metrics(selected),
            **{
                period: _confirmed_event_metrics(
                    [event for event in selected if predicate(event)]
                )
                for period, predicate in periods.items()
            },
        }
        for name, selected in executable_variants.items()
    }
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "method": {
            "entry": "触板事件假设在涨停价成交；收盘封板变体是后验条件事件研究，不是可执行入场信号",
            "floor_entry": "触及跌停事件假设在跌停价买入；跌停是否打开或收盘状态同样属于后验条件",
            "confirmed_entry": "收盘确认后，仅在下一交易日开盘未封涨停且可成交时入场；收益从该开盘价起算",
            "exit": "T+1后按目标开盘/收盘卖出；封死跌停或停牌时顺延至首个可成交日",
            "costs": "股票交易费、印花税和卖出5bp滑点；涨停买入价不额外突破涨停价",
            "mainline_timing": "使用信号日前一交易日收盘可见的前三主线，避免当日收盘信息前视",
            "known_limits": [
                "日K无法还原封单额、排队位置、首次触板和炸板次数；所有成交假设都只是事件收益近似",
                "收盘是否封住只能在收盘后知道；相关正收益只能证明后续影子盘应研究封板质量，不能直接据此下单",
                "当前名称无法完整还原历史ST状态；当前ST和退市名称已排除",
                "主题映射使用当前配置，存在历史成分幸存者偏差",
                "一字涨停的表观收益不可作为可买入收益，未进入可交易候选变体",
                "触及跌停价不等于可按全部计划仓位成交；跌停买入基线同样是乐观成交近似",
                "这是事件收益研究，不是假设无限资金可同时买入所有涨停股的组合净值",
            ],
        },
        "metadata": {**metadata, "train_end": split_60, "validation_end": split_80},
        "variants": variant_metrics,
        "floor_variants": floor_variant_metrics,
        "executable_variants": executable_variant_metrics,
        "path_risks": {name: _event_metrics(selected) for name, selected in path_events.items()},
        "diagnostics": {
            "mainline_first_board_by_year": mainline_yearly,
            "test_mainline_theme_counts": dict(
                sorted(test_theme_counts.items(), key=lambda item: (-item[1], item[0]))
            ),
        },
        "events": [event.to_dict() for event in events],
        "limit_down_events": [event.to_dict() for event in limit_down_events],
    }


def render_limit_up_backtest(report: dict[str, Any]) -> str:
    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value * 100:.2f}%"

    lines = [
        "# A股涨跌停通道事件回测",
        "",
        f"- 区间：`{report['metadata'].get('calendar_start')}` 至 `{report['metadata'].get('calendar_end')}`",
        f"- 有效日历：`{report['metadata'].get('calendar_days')}` 个交易日",
        f"- K线标的：`{report['metadata'].get('symbols_with_klines')}`",
        f"- 观察到涨停触及：`{report['metadata'].get('observed_limit_touches')}` 次",
        f"- 可用事件：`{report['metadata'].get('usable_events')}` 次",
        f"- 观察到跌停触及：`{report['metadata'].get('observed_limit_down_touches')}` 次",
        f"- 可用跌停事件：`{report['metadata'].get('usable_limit_down_events')}` 次",
        f"- 训练/验证分界：`{report['metadata'].get('train_end')}` / `{report['metadata'].get('validation_end')}`",
        "",
        "## 核心变体",
        "",
        "| 变体 | 样本 | 次日开盘均值 | 次日开盘胜率 | 次日收盘均值 | 3日均值 | 5日均值 | 次日跌停 | 退出延迟 | 5日最差路径均值 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, periods in report["variants"].items():
        metrics = periods["all"]
        horizons = metrics["horizons"]
        lines.append(
            f"| {name} | {metrics['signals']} | {pct(horizons['next_open']['average_return'])} | "
            f"{pct(horizons['next_open']['win_rate'])} | {pct(horizons['next_close']['average_return'])} | "
            f"{pct(horizons['day3_close']['average_return'])} | {pct(horizons['day5_close']['average_return'])} | "
            f"{pct(metrics['next_day_limit_down_rate'])} | {pct(metrics['exit_delayed_rate'])} | "
            f"{pct(metrics['average_worst_5d_drawdown'])} |"
        )

    lines.extend(
        [
            "",
            "## 独立跌停板买入事件",
            "",
            "| 变体 | 样本 | 次日开盘均值 | 次日开盘胜率 | 次日收盘均值 | 5日均值 | 次日再跌停 | 退出延迟 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, periods in report.get("floor_variants", {}).items():
        metrics = periods["all"]
        horizons = metrics["horizons"]
        lines.append(
            f"| {name} | {metrics['signals']} | {pct(horizons['next_open']['average_return'])} | "
            f"{pct(horizons['next_open']['win_rate'])} | {pct(horizons['next_close']['average_return'])} | "
            f"{pct(horizons['day5_close']['average_return'])} | "
            f"{pct(metrics['next_day_limit_down_rate'])} | {pct(metrics['exit_delayed_rate'])} |"
        )

    lines.extend(
        [
            "",
            "### 独立跌停板样本外测试",
            "",
            "| 变体 | 测试样本 | 次日开盘均值 | 次日收盘均值 | 5日均值 | 5%尾部 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, periods in report.get("floor_variants", {}).items():
        metrics = periods["test"]
        horizons = metrics["horizons"]
        lines.append(
            f"| {name} | {metrics['signals']} | {pct(horizons['next_open']['average_return'])} | "
            f"{pct(horizons['next_close']['average_return'])} | "
            f"{pct(horizons['day5_close']['average_return'])} | "
            f"{pct(horizons['day5_close']['p05_return'])} |"
        )

    lines.extend(
        [
            "",
            "## 可执行确认后入场（次日开盘）",
            "",
            "收盘确认形态后，下一交易日开盘未封涨停才允许成交；收益从真实次日开盘价起算。",
            "",
            "| 策略 | 全样本可成交 | 测试可成交 | 测试3日胜率 | 测试3日均值 | 测试5日均值 | 测试5%尾部 | 5日最差路径均值 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, periods in report.get("executable_variants", {}).items():
        all_metrics = periods["all"]
        metrics = periods["test"]
        horizons = metrics["horizons"]
        lines.append(
            f"| {name} | {all_metrics['executable_entries']} | {metrics['executable_entries']} | "
            f"{pct(horizons['day3_close']['win_rate'])} | "
            f"{pct(horizons['day3_close']['average_return'])} | "
            f"{pct(horizons['day5_close']['average_return'])} | "
            f"{pct(horizons['day5_close']['p05_return'])} | "
            f"{pct(metrics['average_worst_5d_drawdown'])} |"
        )

    lines.extend(
        [
            "",
            "## 样本外测试",
            "",
            "| 变体 | 测试样本 | 次日开盘均值 | 次日收盘均值 | 5日均值 | 5%尾部 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, periods in report["variants"].items():
        metrics = periods["test"]
        horizons = metrics["horizons"]
        lines.append(
            f"| {name} | {metrics['signals']} | {pct(horizons['next_open']['average_return'])} | "
            f"{pct(horizons['next_close']['average_return'])} | {pct(horizons['day5_close']['average_return'])} | "
            f"{pct(horizons['day5_close']['p05_return'])} |"
        )

    lines.extend(["", "## 天板地板路径", ""])
    for name, metrics in report["path_risks"].items():
        lines.append(
            f"- **{name}**：{metrics['signals']} 次；次日开盘均值 "
            f"{pct(metrics['horizons']['next_open']['average_return'])}；5日均值 "
            f"{pct(metrics['horizons']['day5_close']['average_return'])}；退出延迟 "
            f"{pct(metrics['exit_delayed_rate'])}。"
        )

    lines.extend(
        [
            "",
            "## 主线首板年度稳定性（后验条件）",
            "",
            "| 年份 | 样本 | 次日开盘均值 | 次日收盘均值 | 5日均值 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for year, metrics in report.get("diagnostics", {}).get(
        "mainline_first_board_by_year", {}
    ).items():
        horizons = metrics["horizons"]
        lines.append(
            f"| {year} | {metrics['signals']} | {pct(horizons['next_open']['average_return'])} | "
            f"{pct(horizons['next_close']['average_return'])} | "
            f"{pct(horizons['day5_close']['average_return'])} |"
        )

    lines.extend(
        [
            "",
            "## 口径与限制",
            "",
            f"- {report['method']['entry']}。",
            f"- {report['method']['floor_entry']}。",
            f"- {report['method']['confirmed_entry']}。",
            f"- {report['method']['exit']}。",
            f"- {report['method']['mainline_timing']}。",
        ]
    )
    lines.extend(f"- {item}。" for item in report["method"]["known_limits"])
    return "\n".join(lines) + "\n"
