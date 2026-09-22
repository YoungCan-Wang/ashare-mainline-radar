"""Fibonacci profit-space ranking for the full A-share universe.

Geometry follows the public research notes on the live swing, not a copied
implementation. The lower edge is the 0.382 level measured up from the swing
low. When a prior cause band has converted and is holding as support, that
band's low replaces the Fibonacci level. The upper edge is the supply zone:
its high is the 20-bar high and its low is 97% of that high. Full-box percent
is the distance from the active lower edge up to supply low. Remaining space
is the distance from the last close up to that same supply low. Ranking uses
remaining space, largest first. ST names stay in the universe. This module
does not compute a Wyckoff-funnel cross.
"""

from __future__ import annotations

import math
import os
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable
from urllib.request import urlopen

import numpy as np

from ashare_mainline_radar.engine import _deterministic_cap
from ashare_mainline_radar.models import KlineSeries, cn_market_date_from_ms
from ashare_mainline_radar.supabase_rest import call_rpc
from ashare_mainline_radar.tickflow import TickFlowClient
from ashare_mainline_radar.workflow_frequency import session_as_of

SWING_WINDOW = 60
HIGH_MAX_BARS_AGO = 30
MIN_SWING_AMPLITUDE = 0.20
FIB_FROM_LOW = 0.382
SUPPLY_WINDOW = 20
SUPPLY_ZONE_FACTOR = 0.97
CAUSE_LOOKBACK = 15
MIN_CAUSE_BARS = 8
CAUSE_MAX_RANGE = 0.25
CAUSE_MAX_DRIFT = 0.08
HISTORY_BARS = SWING_WINDOW + CAUSE_LOOKBACK
FETCH_BARS = 120
CI_UNIVERSE_LIMIT = 8
GEOMETRY_VERSION = "fib-box-v1"
UNRUN_STATUS = "未运行"
SUCCESS_STATUS = "成功"
RPC_TIMEOUT_SECONDS = 180


class FibProfitSpaceError(RuntimeError):
    pass


@dataclass
class ProfitSpaceRow:
    code: str
    name: str
    is_st: bool
    close: float | None = None
    fib_or_cause_low: float | None = None
    supply_low: float | None = None
    supply_high: float | None = None
    full_box_pct: float | None = None
    remaining_space_pct: float | None = None
    valid_flag: bool = False
    lower_source: str | None = None
    swing_low: float | None = None
    swing_high: float | None = None
    swing_low_bars_ago: int | None = None
    swing_high_bars_ago: int | None = None
    swing_amplitude: float | None = None
    fib_0382: float | None = None
    cause_low: float | None = None
    cause_high: float | None = None
    cause_is_support: bool = False
    invalid_reason: str | None = None
    last_bar_date: date | None = None
    rank: int | None = None

    def as_db(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "rank": self.rank,
            "close": _round(self.close, 4),
            "fib_or_cause_low": _round(self.fib_or_cause_low, 4),
            "supply_low": _round(self.supply_low, 4),
            "supply_high": _round(self.supply_high, 4),
            "full_box_pct": _round(self.full_box_pct, 8),
            "remaining_space_pct": _round(self.remaining_space_pct, 8),
            "valid_flag": bool(self.valid_flag),
            "lower_source": self.lower_source,
            "swing_low": _round(self.swing_low, 4),
            "swing_high": _round(self.swing_high, 4),
            "swing_low_bars_ago": self.swing_low_bars_ago,
            "swing_high_bars_ago": self.swing_high_bars_ago,
            "swing_amplitude": _round(self.swing_amplitude, 8),
            "fib_0382": _round(self.fib_0382, 4),
            "cause_low": _round(self.cause_low, 4),
            "cause_high": _round(self.cause_high, 4),
            "cause_is_support": bool(self.cause_is_support),
            "is_st": bool(self.is_st),
            "invalid_reason": self.invalid_reason,
            "last_bar_date": self.last_bar_date.isoformat() if self.last_bar_date else None,
        }


@dataclass(frozen=True)
class FibProfitSpaceRun:
    asof_date: date
    rows: list[ProfitSpaceRow]
    universe_id: str

    @property
    def valid_count(self) -> int:
        return sum(1 for row in self.rows if row.valid_flag)

    @property
    def ranked_count(self) -> int:
        return sum(1 for row in self.rows if row.rank is not None)


def name_is_st(name: str) -> bool:
    compact = name.upper().replace(" ", "")
    return compact.startswith("*ST") or compact.startswith("ST")


def resolve_max_symbols(requested: int, *, profile: str) -> int:
    if profile not in {"production", "ci"}:
        raise ValueError(f"unsupported fib universe profile: {profile}")
    if requested < 0:
        raise ValueError("max_symbols cannot be negative")
    if profile == "ci":
        if requested <= 0:
            return CI_UNIVERSE_LIMIT
        return min(requested, CI_UNIVERSE_LIMIT)
    return requested


def select_symbols(symbols: list[str], *, requested: int, profile: str) -> list[str]:
    limit = resolve_max_symbols(requested, profile=profile)
    return _deterministic_cap([str(symbol) for symbol in symbols if symbol], max_symbols=limit, required=[])


def published_board(status: str | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """A missing or failed day is 未运行, even if ranking rows were left behind."""
    if status != SUCCESS_STATUS:
        return {"state": UNRUN_STATUS, "rows": []}
    ranked = [row for row in rows if row.get("valid_flag") and row.get("rank") is not None]
    ranked.sort(key=lambda row: int(row["rank"]))
    return {"state": SUCCESS_STATUS, "rows": ranked}


def clip_series(series: KlineSeries, as_of: date) -> KlineSeries:
    if not series.timestamp:
        return series
    keep = []
    for index, timestamp in enumerate(series.timestamp):
        text = cn_market_date_from_ms(int(timestamp))
        if text and date.fromisoformat(text) <= as_of:
            keep.append(index)

    def _take(values: list[Any]) -> list[Any]:
        return [values[index] for index in keep if index < len(values)]

    return KlineSeries(
        symbol=series.symbol,
        timestamp=_take(series.timestamp),
        open=_take(series.open),
        high=_take(series.high),
        low=_take(series.low),
        close=_take(series.close),
        volume=_take(series.volume),
        amount=_take(series.amount),
        prev_close=_take(series.prev_close),
    )


def last_bar_date(series: KlineSeries) -> date | None:
    if not series.timestamp:
        return None
    text = cn_market_date_from_ms(int(series.timestamp[-1]))
    if not text:
        return None
    return date.fromisoformat(text)


def modal_bar_date(series_map: dict[str, KlineSeries]) -> date | None:
    counts: Counter[date] = Counter()
    for series in series_map.values():
        bar_date = last_bar_date(series)
        if bar_date is not None:
            counts[bar_date] += 1
    if not counts:
        return None
    return max(counts, key=lambda day: (counts[day], day.toordinal()))


def measure_rows(
    items: list[tuple[str, str, KlineSeries]],
    *,
    asof: date | None = None,
) -> list[ProfitSpaceRow]:
    unique: list[tuple[str, str, KlineSeries]] = []
    seen: set[str] = set()
    for code, name, series in items:
        if code in seen:
            continue
        seen.add(code)
        unique.append((code, name, series))
    if not unique:
        return []

    count = len(unique)
    width = HISTORY_BARS
    high = np.full((count, width), np.nan, dtype=float)
    low = np.full((count, width), np.nan, dtype=float)
    close = np.full((count, width), np.nan, dtype=float)
    bar_dates: list[date | None] = []
    for index, (_code, _name, series) in enumerate(unique):
        usable = min(len(series.high), len(series.low), len(series.close))
        bar_dates.append(last_bar_date(series))
        if usable <= 0:
            continue
        take = min(usable, width)
        high[index, width - take :] = np.asarray(series.high[usable - take : usable], dtype=float)
        low[index, width - take :] = np.asarray(series.low[usable - take : usable], dtype=float)
        close[index, width - take :] = np.asarray(series.close[usable - take : usable], dtype=float)

    swing_high_px = high[:, -SWING_WINDOW:]
    swing_low_px = low[:, -SWING_WINDOW:]
    swing_close_px = close[:, -SWING_WINDOW:]
    swing_ok = (
        np.isfinite(swing_high_px).all(axis=1)
        & np.isfinite(swing_low_px).all(axis=1)
        & np.isfinite(swing_close_px).all(axis=1)
        & np.all(swing_high_px + 1e-9 >= swing_low_px, axis=1)
        & np.all(swing_low_px > 0, axis=1)
    )
    with np.errstate(all="ignore"):
        score = np.where(np.isfinite(swing_high_px), swing_high_px, -np.inf)
        high_index = SWING_WINDOW - 1 - np.argmax(score[:, ::-1], axis=1)
        high_price = swing_high_px[np.arange(count), high_index]
        safe_low = np.where(np.isfinite(swing_low_px), swing_low_px, np.inf)
        prefix_min = np.minimum.accumulate(safe_low, axis=1)
        has_prior = high_index > 0
        prior_index = np.clip(high_index - 1, 0, SWING_WINDOW - 1)
        low_price = prefix_min[np.arange(count), prior_index]
        columns = np.arange(SWING_WINDOW)
        before_high = columns[None, :] < high_index[:, None]
        is_swing_low = before_high & np.isfinite(swing_low_px) & (np.abs(swing_low_px - low_price[:, None]) <= 1e-8)
        low_pos = np.where(is_swing_low, columns[None, :], SWING_WINDOW).min(axis=1)
        amplitude = np.where(low_price > 0, (high_price - low_price) / low_price, np.nan)
        fib = low_price + FIB_FROM_LOW * (high_price - low_price)
        supply_high = np.nanmax(high[:, -SUPPLY_WINDOW:], axis=1)
        supply_low = supply_high * SUPPLY_ZONE_FACTOR

        origin = width - SWING_WINDOW
        global_low = np.where(has_prior, origin + low_pos, -1)
        cause_high = np.full(count, np.nan)
        cause_low = np.full(count, np.nan)
        cause_first = np.full(count, np.nan)
        cause_last = np.full(count, np.nan)
        for start in range(width):
            mask = global_low == start
            if not np.any(mask):
                continue
            left = max(0, start - CAUSE_LOOKBACK)
            if start - left < MIN_CAUSE_BARS:
                continue
            segment_high = high[mask, left:start]
            segment_low = low[mask, left:start]
            segment_close = close[mask, left:start]
            finite = (
                np.isfinite(segment_high).all(axis=1)
                & np.isfinite(segment_low).all(axis=1)
                & np.isfinite(segment_close).all(axis=1)
            )
            cause_high[mask] = np.where(finite, np.max(segment_high, axis=1), np.nan)
            cause_low[mask] = np.where(finite, np.min(segment_low, axis=1), np.nan)
            cause_first[mask] = np.where(finite, segment_close[:, 0], np.nan)
            cause_last[mask] = np.where(finite, segment_close[:, -1], np.nan)

        range_pct = np.where(cause_low > 0, (cause_high - cause_low) / cause_low, np.nan)
        drift = np.where(cause_first > 0, np.abs(cause_last - cause_first) / cause_first, np.nan)
        qualified = (
            np.isfinite(range_pct)
            & np.isfinite(drift)
            & (range_pct <= CAUSE_MAX_RANGE)
            & (drift <= CAUSE_MAX_DRIFT)
            & (cause_low > 0)
        )
        finite_high = np.where(np.isfinite(high), high, -np.inf)
        suffix_max = np.maximum.accumulate(finite_high[:, ::-1], axis=1)[:, ::-1]
        finite_close = np.where(np.isfinite(close), close, np.inf)
        suffix_min_close = np.minimum.accumulate(finite_close[:, ::-1], axis=1)[:, ::-1]
        next_pos = np.clip(global_low + 1, 0, width - 1)
        has_after = (global_low >= 0) & (global_low < width - 1)
        max_after = suffix_max[np.arange(count), next_pos]
        min_close_after = suffix_min_close[np.arange(count), next_pos]
        last_close = close[:, -1]
        cause_support = (
            qualified
            & has_after
            & (max_after > cause_high)
            & (min_close_after + 1e-9 >= cause_low)
            & (last_close + 1e-9 >= cause_high)
        )
        use_cause = cause_support & np.isfinite(cause_low) & (cause_low > 0)
        lower = np.where(use_cause, cause_low, fib)
        full_box = np.where(lower > 0, (supply_low - lower) / lower, np.nan)
        remaining = np.where(last_close > 0, (supply_low - last_close) / last_close, np.nan)
        live_high = (SWING_WINDOW - 1 - high_index) <= HIGH_MAX_BARS_AGO
        amplitude_ok = np.isfinite(amplitude) & (amplitude + 1e-12 >= MIN_SWING_AMPLITUDE)

    reasons = np.full(count, "", dtype=object)
    reasons = np.where(~swing_ok, "missing_bars", reasons)
    reasons = np.where((reasons == "") & ~has_prior, "swing_low_missing", reasons)
    reasons = np.where((reasons == "") & ~live_high, "swing_high_not_live", reasons)
    reasons = np.where((reasons == "") & ~amplitude_ok, "swing_too_small", reasons)
    positive = np.isfinite(last_close) & np.isfinite(lower) & (last_close > 0) & (lower > 0)
    reasons = np.where((reasons == "") & ~positive, "non_positive_price", reasons)
    box_ok = np.isfinite(supply_low) & np.isfinite(supply_high) & (supply_high + 1e-9 >= supply_low) & (supply_low > lower)
    reasons = np.where((reasons == "") & ~box_ok, "inverted_box", reasons)
    reasons = np.where((reasons == "") & (last_close + 1e-9 < lower), "broken_support", reasons)
    if asof is not None:
        stale = np.array([bar_date != asof for bar_date in bar_dates])
        reasons = np.where((reasons == "") & stale, "stale_bar", reasons)

    rows: list[ProfitSpaceRow] = []
    for index, (code, name, _series) in enumerate(unique):
        reason = str(reasons[index]) or None
        geometry_ready = reason not in {"missing_bars", "swing_low_missing", "swing_high_not_live", "swing_too_small"}
        row = ProfitSpaceRow(
            code=code,
            name=name,
            is_st=name_is_st(name),
            close=_finite(last_close[index]),
            fib_or_cause_low=_finite(lower[index]) if geometry_ready else None,
            supply_low=_finite(supply_low[index]) if bool(swing_ok[index]) else None,
            supply_high=_finite(supply_high[index]) if bool(swing_ok[index]) else None,
            full_box_pct=_finite(full_box[index]) if geometry_ready else None,
            remaining_space_pct=_finite(remaining[index]) if geometry_ready else None,
            valid_flag=reason is None,
            lower_source=("cause" if bool(use_cause[index]) else "fib_0382") if geometry_ready else None,
            swing_low=_finite(low_price[index]) if bool(has_prior[index] and swing_ok[index]) else None,
            swing_high=_finite(high_price[index]) if bool(swing_ok[index]) else None,
            swing_low_bars_ago=int(width - 1 - global_low[index]) if bool(has_prior[index] and swing_ok[index]) else None,
            swing_high_bars_ago=int(SWING_WINDOW - 1 - high_index[index]) if bool(swing_ok[index]) else None,
            swing_amplitude=_finite(amplitude[index]) if bool(has_prior[index] and swing_ok[index]) else None,
            fib_0382=_finite(fib[index]) if bool(has_prior[index] and swing_ok[index]) else None,
            cause_low=_finite(cause_low[index]),
            cause_high=_finite(cause_high[index]),
            cause_is_support=bool(cause_support[index]),
            invalid_reason=reason,
            last_bar_date=bar_dates[index],
        )
        rows.append(row)
    _assign_ranks(rows)
    return rows


def build_fib_profit_space(
    *,
    client: TickFlowClient,
    max_symbols: int = 0,
    profile: str = "production",
    universe_id: str = "CN_Equity_A",
    as_of: date | None = None,
) -> FibProfitSpaceRun:
    universe = client.get_universe(universe_id)
    symbols = select_symbols([str(symbol) for symbol in universe.get("symbols") or []], requested=max_symbols, profile=profile)
    if not symbols:
        raise FibProfitSpaceError("A-share universe is empty")
    instruments = client.get_instruments(symbols)
    klines = client.get_klines_batch(symbols, period="1d", count=FETCH_BARS, adjust="forward")
    covered = sum(1 for symbol in symbols if symbol in klines and klines[symbol].close)
    if covered * 2 < len(symbols):
        raise FibProfitSpaceError(f"bar coverage {covered}/{len(symbols)} is below half the universe")
    if as_of is not None:
        klines = {symbol: clip_series(series, as_of) for symbol, series in klines.items()}
        asof = as_of
    else:
        asof = modal_bar_date(klines)
        if asof is None:
            raise FibProfitSpaceError("daily bars did not include a market date")
        klines = {symbol: clip_series(series, asof) for symbol, series in klines.items()}
    items = []
    for symbol in symbols:
        instrument = instruments.get(symbol) or {}
        name = str(instrument.get("name") or "")
        series = klines.get(symbol) or KlineSeries(symbol, [], [], [], [], [], [], [])
        items.append((symbol, name, series))
    rows = measure_rows(items, asof=asof)
    if len(rows) != len(symbols):
        raise FibProfitSpaceError("ranking did not cover every selected symbol")
    return FibProfitSpaceRun(asof_date=asof, rows=rows, universe_id=universe_id)


def persist_fib_profit_space(
    *,
    supabase_url: str,
    supabase_publishable_key: str,
    radar_ingest_key: str,
    run: FibProfitSpaceRun | None,
    status: str,
    message: str,
    asof: date,
    opener: Callable[..., Any] = urlopen,
) -> None:
    if status == SUCCESS_STATUS:
        if run is None or not run.rows:
            raise FibProfitSpaceError("refusing empty fib ranking")
        rows = [row.as_db() for row in run.rows]
        asof = run.asof_date
    elif status == UNRUN_STATUS:
        rows = []
    else:
        raise FibProfitSpaceError(f"unsupported fib status: {status}")
    call_rpc(
        supabase_url,
        supabase_publishable_key,
        radar_ingest_key,
        "apply_fib_profit_space_day",
        {
            "p_asof": asof.isoformat(),
            "p_rows": rows,
            "p_status": status,
            "p_message": message,
        },
        opener=opener,
        timeout=RPC_TIMEOUT_SECONDS,
    )


def failure_asof(now: datetime | None = None) -> date:
    return session_as_of(now or datetime.now(timezone.utc))


def supabase_credentials() -> tuple[str, str, str]:
    url = os.getenv("SUPABASE_URL")
    api_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")
    ingest_key = os.getenv("RADAR_INGEST_KEY")
    if not url or not api_key or not ingest_key:
        raise FibProfitSpaceError("SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and RADAR_INGEST_KEY are required")
    return url, api_key, ingest_key


def _assign_ranks(rows: list[ProfitSpaceRow]) -> None:
    ranked = [row for row in rows if row.valid_flag and row.remaining_space_pct is not None]
    ranked.sort(key=lambda row: (-float(row.remaining_space_pct or 0.0), row.code))
    ranked_codes = {row.code for row in ranked}
    for row in rows:
        row.rank = None
        row.valid_flag = row.code in ranked_codes
    for rank, row in enumerate(ranked, start=1):
        row.rank = rank
        row.valid_flag = True


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _round(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)
