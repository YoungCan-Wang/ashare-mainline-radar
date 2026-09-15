from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from math import floor
from random import Random
from statistics import fmean, mean, median
from typing import Any

from .execution import (
    TradingCostModel,
    apply_execution_costs,
    daily_limit_price,
    price_limit_rate,
)
from .models import KlineSeries, cn_market_date_from_ms


@dataclass(frozen=True)
class VolumeLagRules:
    min_amount_ratio: float = 1.50
    min_amount_percentile: float = 0.80
    volume_combine: str = "or"
    min_ret_1d: float = -0.01
    max_ret_1d: float = 0.02
    max_ret_5d: float = 0.08
    max_high_proximity_20d: float = -0.03
    max_range_position_60d: float = 0.70
    low_base_max_range: float = 0.55
    high_base_min_range: float = 0.70
    max_per_day: int = 12
    hold_days: tuple[int, ...] = (1, 3, 5)
    random_seed: int = 7
    sample_out_fraction: float = 0.30
    min_test_trades: int = 80
    min_mean_net: float = 0.001
    position_fraction: float = 0.03
    warmup_days: int = 60

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BarFeatures:
    symbol: str
    name: str
    timestamp: int
    signal_date: str
    close: float
    amount: float
    ret_1d: float
    ret_5d: float
    amount_ratio: float
    amount_ratio_5_20: float
    high_proximity_20d: float
    range_position_60d: float
    is_limit_up: bool
    is_one_price: bool
    amount_percentile: float = 0.0

    @property
    def cohort(self) -> str:
        if self.range_position_60d > 0.70:
            return "high_base"
        if self.range_position_60d <= 0.55:
            return "low_base"
        return "mid_base"

    def volume_ok(self, rules: VolumeLagRules) -> bool:
        ratio_ok = self.amount_ratio >= rules.min_amount_ratio
        percentile_ok = self.amount_percentile >= rules.min_amount_percentile
        if rules.volume_combine == "and":
            return ratio_ok and percentile_ok
        return ratio_ok or percentile_ok

    def volume_price_ok(self, rules: VolumeLagRules) -> bool:
        return (
            not self.is_limit_up
            and not self.is_one_price
            and self.volume_ok(rules)
            and rules.min_ret_1d <= self.ret_1d <= rules.max_ret_1d
            and self.ret_5d <= rules.max_ret_5d
        )

    def lag_structure_ok(self, rules: VolumeLagRules) -> bool:
        return self.high_proximity_20d <= rules.max_high_proximity_20d

    def rank_score(self) -> float:
        return (
            min(2.0, max(0.0, self.amount_ratio - 1.0)) * 20.0
            + self.amount_percentile * 30.0
            + (1.0 - self.range_position_60d) * 20.0
        )


@dataclass
class VolumeLagTrade:
    strategy: str
    cohort: str
    symbol: str
    name: str
    signal_date: str
    entry_date: str | None
    exit_date: str | None
    horizon: int
    entry_mode: str
    net_return: float | None
    path_drawdown: float | None
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HorizonMetrics:
    trades: int
    blocked: int
    win_rate: float | None
    mean_return: float | None
    median_return: float | None
    p05_return: float | None
    avg_path_drawdown: float | None

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


def _stock_name(instrument: dict[str, Any] | None, symbol: str) -> str:
    instrument = instrument or {}
    return str(instrument.get("name") or instrument.get("display_name") or symbol)


def is_research_stock(symbol: str, instrument: dict[str, Any] | None) -> bool:
    if not symbol.endswith((".SH", ".SZ", ".BJ")):
        return False
    name = _stock_name(instrument, symbol)
    upper = name.upper()
    if any(token in upper for token in ("ETF", "LOF", "REIT")):
        return False
    if any(token in name for token in ("指数", "基金", "转债", "退")):
        return False
    return True


def is_known_st(name: str) -> bool:
    upper = name.upper().replace(" ", "")
    return upper.startswith(("ST", "*ST"))


def _avg(values: list[float]) -> float | None:
    usable = [value for value in values if value > 0]
    return mean(usable) if usable else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * quantile
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    weight = index - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _percentile_ranks(values: list[float]) -> list[float]:
    count = len(values)
    if count == 0:
        return []
    if count == 1:
        return [1.0]
    order = sorted(range(count), key=lambda index: values[index])
    ranks = [0.0] * count
    for rank, index in enumerate(order):
        ranks[index] = rank / (count - 1)
    return ranks


def _day_rng(signal_date: str, seed: int) -> Random:
    digest = sha256(f"{seed}:{signal_date}".encode()).digest()
    return Random(int.from_bytes(digest[:8], "little"))


def _calendar(klines: dict[str, KlineSeries]) -> list[int]:
    counts: dict[int, int] = {}
    for series in klines.values():
        for timestamp in series.timestamp:
            counts[timestamp] = counts.get(timestamp, 0) + 1
    if not counts:
        return []
    minimum = max(1, floor(len(klines) * 0.35))
    return sorted(timestamp for timestamp, count in counts.items() if count >= minimum)


def features_at(
    series: KlineSeries,
    index: int,
    symbol: str,
    name: str,
) -> BarFeatures | None:
    if index < 60:
        return None
    bar = _bar(series, index)
    previous = _bar(series, index - 1)
    if bar is None or previous is None or bar["close"] <= 0 or previous["close"] <= 0 or bar["volume"] <= 0:
        return None
    if index >= len(series.timestamp):
        return None
    signal_date = cn_market_date_from_ms(series.timestamp[index])
    if signal_date is None:
        return None
    if index < 5 or series.close[index - 5] <= 0:
        return None
    amount_baseline = _avg(series.amount[index - 20 : index])
    amount_ma5 = _avg(series.amount[index - 4 : index + 1])
    amount_ma20 = _avg(series.amount[index - 19 : index + 1])
    if amount_baseline is None or amount_ma5 is None or amount_ma20 is None:
        return None
    high_20d = max(series.high[index - 19 : index + 1])
    high_60d = max(series.high[index - 59 : index + 1])
    low_60d = min(series.low[index - 59 : index + 1])
    if high_20d <= 0 or high_60d <= low_60d:
        return None
    reference = (
        series.prev_close[index]
        if index < len(series.prev_close) and series.prev_close[index] > 0
        else previous["close"]
    )
    upper = daily_limit_price(reference, price_limit_rate(symbol, name, signal_date), direction="up")
    one_price = (
        abs(bar["high"] - bar["low"]) <= 0.005
        and abs(bar["open"] - bar["close"]) <= 0.005
        and abs(bar["high"] - bar["close"]) <= 0.005
    )
    return BarFeatures(
        symbol=symbol,
        name=name,
        timestamp=series.timestamp[index],
        signal_date=signal_date,
        close=bar["close"],
        amount=bar["amount"],
        ret_1d=bar["close"] / previous["close"] - 1,
        ret_5d=bar["close"] / series.close[index - 5] - 1,
        amount_ratio=bar["amount"] / amount_baseline,
        amount_ratio_5_20=amount_ma5 / amount_ma20,
        high_proximity_20d=bar["close"] / high_20d - 1,
        range_position_60d=(bar["close"] - low_60d) / (high_60d - low_60d),
        is_limit_up=bar["close"] >= upper - 0.005,
        is_one_price=one_price,
    )


def _metrics(trades: list[VolumeLagTrade]) -> HorizonMetrics:
    blocked = sum(1 for trade in trades if trade.blocked_reason)
    active = [trade for trade in trades if trade.net_return is not None]
    returns = [float(trade.net_return) for trade in active]
    drawdowns = [float(trade.path_drawdown) for trade in active if trade.path_drawdown is not None]
    if not returns:
        return HorizonMetrics(0, blocked, None, None, None, None, None)
    wins = sum(1 for value in returns if value > 0)
    return HorizonMetrics(
        trades=len(returns),
        blocked=blocked,
        win_rate=wins / len(returns),
        mean_return=fmean(returns),
        median_return=median(returns),
        p05_return=_percentile(returns, 0.05),
        avg_path_drawdown=fmean(drawdowns) if drawdowns else None,
    )


def _in_period(signal_date: str, start: str | None, end: str | None) -> bool:
    if start and signal_date < start:
        return False
    if end and signal_date > end:
        return False
    return True


def _horizon_table(
    trades: list[VolumeLagTrade],
    *,
    strategy: str | None = None,
    cohort: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    table: dict[str, dict[str, dict[str, Any]]] = {}
    for entry_mode in ("next_open", "close_to_close"):
        table[entry_mode] = {}
        horizons = sorted({trade.horizon for trade in trades if trade.entry_mode == entry_mode})
        for horizon in horizons:
            rows = [
                trade
                for trade in trades
                if trade.entry_mode == entry_mode
                and trade.horizon == horizon
                and (strategy is None or trade.strategy == strategy)
                and (cohort is None or trade.cohort == cohort)
                and _in_period(trade.signal_date, start, end)
            ]
            table[entry_mode][str(horizon)] = _metrics(rows).to_dict()
    return table


def _evaluate_path(
    series: KlineSeries,
    signal_index: int,
    hold: int,
    entry_mode: str,
    symbol: str,
    name: str,
    cost_model: TradingCostModel,
    position_fraction: float,
) -> tuple[str | None, str | None, float | None, float | None, str | None]:
    if hold <= 0 or signal_index + hold >= len(series.close):
        return None, None, None, None, "missing_forward_bars"
    if entry_mode == "next_open":
        entry_index = signal_index + 1
        exit_index = signal_index + hold
        entry_bar = _bar(series, entry_index)
        if entry_bar is None or entry_bar["open"] <= 0 or entry_bar["volume"] <= 0:
            return None, None, None, None, "next_session_suspended_or_missing"
        previous = _bar(series, signal_index)
        entry_date = cn_market_date_from_ms(series.timestamp[entry_index])
        if previous is None or previous["close"] <= 0 or entry_date is None:
            return None, None, None, None, "missing_entry_reference"
        reference = (
            series.prev_close[entry_index]
            if entry_index < len(series.prev_close) and series.prev_close[entry_index] > 0
            else previous["close"]
        )
        upper = daily_limit_price(reference, price_limit_rate(symbol, name, entry_date), direction="up")
        if entry_bar["open"] >= upper - 0.005:
            return None, None, None, None, "next_open_at_limit_up"
        raw_entry = entry_bar["open"]
    else:
        entry_index = signal_index
        exit_index = signal_index + hold
        close_bar = _bar(series, entry_index)
        entry_date = cn_market_date_from_ms(series.timestamp[entry_index])
        if close_bar is None or close_bar["close"] <= 0 or entry_date is None:
            return None, None, None, None, "missing_signal_close"
        raw_entry = close_bar["close"]

    exit_bar = _bar(series, exit_index)
    exit_date = cn_market_date_from_ms(series.timestamp[exit_index]) if exit_index < len(series.timestamp) else None
    if exit_bar is None or exit_bar["close"] <= 0 or exit_date is None:
        return entry_date, None, None, None, "missing_exit_bar"
    costs = apply_execution_costs(
        raw_entry,
        exit_bar["close"],
        entry_date or "",
        exit_date,
        cost_model.account_capital * position_fraction,
        is_fund=False,
        cost_model=cost_model,
    )
    lows = [value for value in series.low[entry_index : exit_index + 1] if value > 0]
    drawdown = (min(lows) / raw_entry - 1) if lows else None
    return entry_date, exit_date, float(costs["net_return"]), drawdown, None


def _accumulation_like(feature: BarFeatures) -> bool:
    return (
        not feature.is_limit_up
        and not feature.is_one_price
        and feature.range_position_60d <= 0.58
        and feature.amount_ratio_5_20 >= 1.08
        and feature.ret_5d >= -0.03
    )


def _pick(features: list[BarFeatures], limit: int) -> list[BarFeatures]:
    ranked = sorted(features, key=lambda item: item.rank_score(), reverse=True)
    return ranked[:limit]


def _append_trades(
    trades: list[VolumeLagTrade],
    features: list[BarFeatures],
    strategy: str,
    klines: dict[str, KlineSeries],
    lookups: dict[str, dict[int, int]],
    rules: VolumeLagRules,
    cost_model: TradingCostModel,
) -> None:
    for feature in features:
        series = klines[feature.symbol]
        index = lookups[feature.symbol][feature.timestamp]
        for entry_mode in ("next_open", "close_to_close"):
            for hold in rules.hold_days:
                entry_date, exit_date, net_return, drawdown, blocked = _evaluate_path(
                    series,
                    index,
                    hold,
                    entry_mode,
                    feature.symbol,
                    feature.name,
                    cost_model,
                    rules.position_fraction,
                )
                trades.append(
                    VolumeLagTrade(
                        strategy=strategy,
                        cohort=feature.cohort,
                        symbol=feature.symbol,
                        name=feature.name,
                        signal_date=feature.signal_date,
                        entry_date=entry_date,
                        exit_date=exit_date,
                        horizon=hold,
                        entry_mode=entry_mode,
                        net_return=net_return,
                        path_drawdown=drawdown,
                        blocked_reason=blocked,
                    )
                )


def collect_volume_lag_trades(
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    *,
    rules: VolumeLagRules | None = None,
    cost_model: TradingCostModel | None = None,
) -> tuple[list[VolumeLagTrade], dict[str, Any]]:
    rules = rules or VolumeLagRules()
    cost_model = cost_model or TradingCostModel()
    calendar = _calendar(klines)
    lookups = {symbol: {ts: idx for idx, ts in enumerate(series.timestamp)} for symbol, series in klines.items()}
    names = {
        symbol: _stock_name(instruments.get(symbol), symbol)
        for symbol in klines
        if is_research_stock(symbol, instruments.get(symbol)) and not is_known_st(_stock_name(instruments.get(symbol), symbol))
    }
    trades: list[VolumeLagTrade] = []
    signal_dates: list[str] = []
    selected_days = 0
    skipped_high_base = 0
    eligible_days = 0

    for calendar_index, timestamp in enumerate(calendar):
        if calendar_index < rules.warmup_days or calendar_index + max(rules.hold_days) >= len(calendar):
            continue
        cross_section: list[BarFeatures] = []
        for symbol, name in names.items():
            index = lookups[symbol].get(timestamp)
            if index is None:
                continue
            feature = features_at(klines[symbol], index, symbol, name)
            if feature is not None:
                cross_section.append(feature)
        if len(cross_section) < 8:
            continue
        ranks = _percentile_ranks([item.amount for item in cross_section])
        cross_section = [
            BarFeatures(**{**asdict(item), "amount_percentile": ranks[idx]})
            for idx, item in enumerate(cross_section)
        ]
        eligible_days += 1
        core = [item for item in cross_section if item.volume_price_ok(rules)]
        volume_lag = [
            item
            for item in core
            if item.lag_structure_ok(rules) and item.range_position_60d <= rules.max_range_position_60d
        ]
        high_base = [item for item in core if item.range_position_60d > rules.high_base_min_range]
        skipped_high_base += len(high_base)
        picked = _pick(volume_lag, rules.max_per_day)
        if picked:
            selected_days += 1
            signal_dates.append(picked[0].signal_date)
        _append_trades(trades, picked, "volume_lag", klines, lookups, rules, cost_model)
        _append_trades(trades, _pick(high_base, rules.max_per_day), "high_base_lag", klines, lookups, rules, cost_model)

        count = len(picked)
        if count <= 0:
            continue
        rng = _day_rng(picked[0].signal_date, rules.random_seed)
        random_pool = [item for item in cross_section if not item.is_limit_up and not item.is_one_price]
        random_picks = rng.sample(random_pool, k=min(count, len(random_pool))) if random_pool else []
        amount_picks = sorted(random_pool, key=lambda item: item.amount, reverse=True)[:count]
        accumulation_picks = _pick([item for item in cross_section if _accumulation_like(item)], count)
        _append_trades(trades, random_picks, "random_same_size", klines, lookups, rules, cost_model)
        _append_trades(trades, amount_picks, "amount_topn", klines, lookups, rules, cost_model)
        _append_trades(trades, accumulation_picks, "accumulation_like", klines, lookups, rules, cost_model)

    metadata = {
        "calendar_start": cn_market_date_from_ms(calendar[rules.warmup_days]) if len(calendar) > rules.warmup_days else None,
        "calendar_end": cn_market_date_from_ms(calendar[-1]) if calendar else None,
        "calendar_days": max(0, len(calendar) - rules.warmup_days),
        "eligible_cross_section_days": eligible_days,
        "selected_days": selected_days,
        "signal_dates": signal_dates,
        "symbols_scanned": len(names),
        "high_base_core_hits": skipped_high_base,
        "cost_assumptions": cost_model.assumptions(),
    }
    return trades, metadata


def _split_bounds(dates: list[str], sample_out_fraction: float) -> dict[str, str | None]:
    unique = sorted(dict.fromkeys(dates))
    if not unique:
        return {"train_end": None, "test_start": None, "test_end": None}
    cut = max(1, int(len(unique) * (1.0 - sample_out_fraction)))
    if cut >= len(unique):
        cut = len(unique) - 1
    return {
        "train_end": unique[cut - 1],
        "test_start": unique[cut],
        "test_end": unique[-1],
    }


def _walk_forward_steps(dates: list[str], steps: int = 3) -> list[dict[str, str]]:
    unique = sorted(dict.fromkeys(dates))
    if len(unique) < steps + 1:
        return []
    size = max(1, len(unique) // (steps + 1))
    result: list[dict[str, str]] = []
    for index in range(1, steps + 1):
        train_end_idx = min(len(unique) - 2, size * index - 1)
        test_start_idx = train_end_idx + 1
        test_end_idx = min(len(unique) - 1, size * (index + 1) - 1)
        if test_start_idx > test_end_idx:
            continue
        result.append(
            {
                "name": f"step_{index}",
                "train_end": unique[train_end_idx],
                "test_start": unique[test_start_idx],
                "test_end": unique[test_end_idx],
            }
        )
    return result


def decide_collection_verdict(
    low_base_test: HorizonMetrics,
    overall_test: HorizonMetrics,
    amount_test: HorizonMetrics,
    random_test: HorizonMetrics,
    *,
    min_trades: int,
    min_mean_net: float,
) -> dict[str, Any]:
    def _beats(candidate: HorizonMetrics, baseline: HorizonMetrics) -> bool:
        if candidate.mean_return is None or baseline.mean_return is None:
            return False
        return candidate.mean_return > baseline.mean_return

    def _passes(candidate: HorizonMetrics) -> bool:
        return (
            candidate.trades >= min_trades
            and candidate.mean_return is not None
            and candidate.mean_return >= min_mean_net
        )

    low_ok = _passes(low_base_test)
    overall_ok = _passes(overall_test)
    low_beats = _beats(low_base_test, amount_test) and _beats(low_base_test, random_test)
    overall_beats = _beats(overall_test, amount_test) and _beats(overall_test, random_test)
    if low_ok and low_beats:
        decision = "GO"
        reason = "样本外低位 volume_lag 扣费后均值显著为正，且优于成交额 TopN 与同规模随机。"
    elif overall_ok and overall_beats:
        decision = "GO"
        reason = "样本外全体 volume_lag 扣费后均值显著为正，且优于两条基线；低位子集未单独过线。"
    else:
        decision = "NO-GO"
        reason = (
            "样本外扣费后期望不够正，或交易笔数不足，或未能稳定优于成交额 TopN / 随机基线；"
            "不建议写入 Daily 采集。"
        )
    return {
        "decision": decision,
        "reason": reason,
        "primary_horizon": "next_open_5",
        "low_base_passes": low_ok,
        "overall_passes": overall_ok,
        "low_base_beats_baselines": low_beats,
        "overall_beats_baselines": overall_beats,
        "collect_into_daily": False if decision == "NO-GO" else True,
    }


def _metrics_from_table(table: dict[str, dict[str, dict[str, Any]]], entry_mode: str, horizon: str) -> HorizonMetrics:
    payload = table.get(entry_mode, {}).get(horizon, {})
    return HorizonMetrics(
        trades=int(payload.get("trades") or 0),
        blocked=int(payload.get("blocked") or 0),
        win_rate=payload.get("win_rate"),
        mean_return=payload.get("mean_return"),
        median_return=payload.get("median_return"),
        p05_return=payload.get("p05_return"),
        avg_path_drawdown=payload.get("avg_path_drawdown"),
    )


def build_volume_lag_report(
    trades: list[VolumeLagTrade],
    metadata: dict[str, Any],
    *,
    rules: VolumeLagRules | None = None,
) -> dict[str, Any]:
    rules = rules or VolumeLagRules()
    signal_dates = [str(item) for item in metadata.get("signal_dates") or []]
    split = _split_bounds(signal_dates, rules.sample_out_fraction)
    train_end = split["train_end"]
    test_start = split["test_start"]
    test_end = split["test_end"]

    def pack(strategy: str, cohort: str | None = None) -> dict[str, Any]:
        return {
            "all": _horizon_table(trades, strategy=strategy, cohort=cohort),
            "train": _horizon_table(trades, strategy=strategy, cohort=cohort, end=train_end),
            "test": _horizon_table(trades, strategy=strategy, cohort=cohort, start=test_start, end=test_end),
        }

    strategies = {
        "volume_lag": pack("volume_lag"),
        "volume_lag_low_base": pack("volume_lag", "low_base"),
        "volume_lag_mid_base": pack("volume_lag", "mid_base"),
        "high_base_lag": pack("high_base_lag", "high_base"),
        "random_same_size": pack("random_same_size"),
        "amount_topn": pack("amount_topn"),
        "accumulation_like": pack("accumulation_like"),
    }
    walk_forward = []
    for step in _walk_forward_steps(signal_dates):
        table = _horizon_table(
            trades,
            strategy="volume_lag",
            cohort="low_base",
            start=step["test_start"],
            end=step["test_end"],
        )
        walk_forward.append({**step, "low_base_next_open_5": table.get("next_open", {}).get("5")})

    verdict = decide_collection_verdict(
        _metrics_from_table(strategies["volume_lag_low_base"]["test"], "next_open", "5"),
        _metrics_from_table(strategies["volume_lag"]["test"], "next_open", "5"),
        _metrics_from_table(strategies["amount_topn"]["test"], "next_open", "5"),
        _metrics_from_table(strategies["random_same_size"]["test"], "next_open", "5"),
        min_trades=rules.min_test_trades,
        min_mean_net=rules.min_mean_net,
    )
    return {
        "role": "volume_lag",
        "layer": "observation_research_only",
        "feeds_next_buy": False,
        "persist_to_supabase": False,
        "theme_boost": "skipped_v1",
        "rules": rules.to_dict(),
        "metadata": {key: value for key, value in metadata.items() if key != "signal_dates"},
        "split": split,
        "strategies": strategies,
        "walk_forward": walk_forward,
        "verdict": verdict,
        "trade_count": len(trades),
    }


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _row(metrics: dict[str, Any]) -> str:
    return (
        f"{metrics.get('trades', 0)} | {_pct(metrics.get('win_rate'))} | {_pct(metrics.get('mean_return'))} | "
        f"{_pct(metrics.get('median_return'))} | {_pct(metrics.get('p05_return'))} | "
        f"{_pct(metrics.get('avg_path_drawdown'))}"
    )


def render_volume_lag_backtest(report: dict[str, Any]) -> str:
    rules = report["rules"]
    split = report["split"]
    verdict = report["verdict"]
    meta = report["metadata"]
    strategies = report["strategies"]

    def cell(strategy: str, period: str, mode: str = "next_open", horizon: str = "5") -> dict[str, Any]:
        return strategies[strategy][period].get(mode, {}).get(horizon, {})

    lines = [
        "# volume_lag（量先行/滞涨观察）研究回测",
        "",
        "这是观察层（observation layer，只看不买）研究，不写入 Daily 选股，不进 `next_buy`，不落 Supabase。",
        "",
        "## 规则",
        "",
        f"- 成交额：当日成交额/自身近20日均值 ≥ {rules['min_amount_ratio']:.2f}x，或全市场分位 ≥ {rules['min_amount_percentile']:.0%}（`{rules['volume_combine']}`）。",
        f"- 价格滞后：当日涨跌 ∈ [{rules['min_ret_1d']:+.1%}, {rules['max_ret_1d']:+.1%}]，5日涨幅 ≤ {rules['max_ret_5d']:.1%}，距20日高点 ≤ {rules['max_high_proximity_20d']:.1%}。",
        f"- 位置：主信号 60日区间位置 ≤ {rules['max_range_position_60d']:.0%}；低位队列 ≤ {rules['low_base_max_range']:.0%}；高于 {rules['high_base_min_range']:.0%} 记为高位滞涨/出货风险，不进主信号。",
        "- 排除 ST/ETF/涨停收盘/一字板。v1 不做主线主题加权。",
        "- 入场：下一交易日开盘（涨停开盘不成交）；持有 1/3/5 个交易日收盘卖出；费用复用 `TradingCostModel`。",
        f"- 每日最多 {rules['max_per_day']} 只。低位/高位分队列报告。",
        "",
        "## 样本",
        "",
        f"- 扫描标的 {meta.get('symbols_scanned')} 只，可用截面日 {meta.get('eligible_cross_section_days')}，有信号日 {meta.get('selected_days')}。",
        f"- 日历 {meta.get('calendar_start')} 至 {meta.get('calendar_end')}（warmup {rules['warmup_days']} 日）。",
        f"- 样本外（sample-out，留出检验）：训练截至 {split.get('train_end')}，检验 {split.get('test_start')} 至 {split.get('test_end')}。",
        "",
        "## 主口径：次日开盘 → 5日收盘（扣费后）",
        "",
        "| 队列 | 期 | 笔数 | 胜率 | 均值 | 中位数 | p05 | 路径回撤 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for label, key in (
        ("volume_lag 全体", "volume_lag"),
        ("volume_lag 低位", "volume_lag_low_base"),
        ("volume_lag 中位", "volume_lag_mid_base"),
        ("高位滞涨", "high_base_lag"),
        ("成交额 TopN", "amount_topn"),
        ("同规模随机", "random_same_size"),
        ("accumulation 近似", "accumulation_like"),
    ):
        for period, period_label in (("all", "全期"), ("train", "训练"), ("test", "样本外")):
            lines.append(f"| {label} | {period_label} | {_row(cell(key, period))} |")

    lines.extend(
        [
            "",
            "## 其它持有期（volume_lag 全体 / 次日开盘 / 样本外）",
            "",
            "| 持有 | 笔数 | 胜率 | 均值 | 中位数 | p05 | 路径回撤 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for horizon in ("1", "3", "5"):
        lines.append(f"| {horizon}日 | {_row(cell('volume_lag', 'test', 'next_open', horizon))} |")

    lines.extend(["", "## 滚动前进（walk-forward，低位 next_open 5日）", ""])
    if report.get("walk_forward"):
        lines.append("| 步骤 | 训练截止 | 检验区间 | 笔数 | 均值 | 胜率 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for step in report["walk_forward"]:
            metrics = step.get("low_base_next_open_5") or {}
            lines.append(
                f"| {step['name']} | {step['train_end']} | {step['test_start']} 至 {step['test_end']} | "
                f"{metrics.get('trades', 0)} | {_pct(metrics.get('mean_return'))} | {_pct(metrics.get('win_rate'))} |"
            )
    else:
        lines.append("样本日不足，未切滚动折。")

    lines.extend(
        [
            "",
            "## 结论",
            "",
            f"**{verdict['decision']}**：{verdict['reason']}",
            "",
            "- 过线条件：样本外低位或全体，次日开盘持有5日，扣费后均值 ≥ 10bp，笔数 ≥ 80，且同时高于成交额 TopN 与同规模随机。",
            "- 高位放量不涨单独标记，不作为采集理由。",
            "- 即使 GO，也只表示值得进入 Daily 观察层评估，不是买入通道。",
        ]
    )
    return "\n".join(lines) + "\n"


def run_volume_lag_backtest(
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    *,
    rules: VolumeLagRules | None = None,
    cost_model: TradingCostModel | None = None,
) -> dict[str, Any]:
    rules = rules or VolumeLagRules()
    trades, metadata = collect_volume_lag_trades(klines, instruments, rules=rules, cost_model=cost_model)
    return build_volume_lag_report(trades, metadata, rules=rules)
