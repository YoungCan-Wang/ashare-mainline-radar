from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.request import urlopen

from .execution import (
    TradeExecutionPlan,
    TradingCostModel,
    apply_execution_costs,
    entry_confirmed,
    is_fund_security,
    is_sealed_limit_down,
    is_sealed_limit_up,
)
from .models import KlineSeries, cn_market_date_from_ms
from .paper_strategies import PRODUCTION_PAPER_STRATEGY
from .supabase_rest import fetch_rows, upsert_rows
from .tickflow import TickFlowClient


@dataclass(frozen=True)
class PaperTradeRefreshStatus:
    status: str
    plans_checked: int
    plans_updated: int
    events_written: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dates(series: KlineSeries) -> list[str]:
    return [cn_market_date_from_ms(value) or "" for value in series.timestamp]


def _bar(series: KlineSeries, index: int) -> dict[str, float]:
    return {
        "open": series.open[index],
        "high": series.high[index],
        "low": series.low[index],
        "close": series.close[index],
        "volume": series.volume[index],
    }


def _event(plan: dict[str, Any], event_type: str, event_date: str, price: float | None, **payload: Any) -> dict[str, Any]:
    return {
        "event_key": f"{plan['plan_key']}:{event_type}:{event_date}",
        "plan_key": plan["plan_key"],
        "symbol": plan["symbol"],
        "strategy_version": plan.get("strategy_version") or PRODUCTION_PAPER_STRATEGY.version,
        "event_type": event_type,
        "event_date": event_date,
        "price": price,
        "payload": payload,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _execution_plan(row: dict[str, Any]) -> TradeExecutionPlan:
    return TradeExecutionPlan(
        entry_mode=str(row["entry_mode"]),
        entry_zone_low=float(row["entry_zone_low"]),
        entry_zone_high=float(row["entry_zone_high"]),
        confirm_price=float(row["confirm_price"]),
        stop_price=float(row["stop_price"]),
        valid_for_days=int(row["valid_for_days"]),
        max_hold_days=int(row["max_hold_days"]),
        max_position_fraction=float(row["max_position_fraction"]),
        initial_position_fraction=float(row["initial_position_fraction"]),
    )


def _evaluate_entry(
    plan: dict[str, Any], series: KlineSeries, cost_model: TradingCostModel
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dates = _dates(series)
    if str(plan["signal_date"]) not in dates:
        return plan, []
    signal_index = dates.index(str(plan["signal_date"]))
    execution = _execution_plan(plan)
    events: list[dict[str, Any]] = []
    trigger_index: int | None = None
    stored_trigger = str(plan.get("trigger_date") or "")
    if stored_trigger in dates:
        trigger_index = dates.index(stored_trigger)
    else:
        last_trigger = min(signal_index + execution.valid_for_days, len(dates) - 1)
        for index in range(signal_index + 1, last_trigger + 1):
            bar = _bar(series, index)
            if entry_confirmed(
                execution,
                day_open=bar["open"],
                day_high=bar["high"],
                day_low=bar["low"],
                day_close=bar["close"],
            ):
                trigger_index = index
                plan.update(status="triggered", trigger_date=dates[index], updated_at=datetime.now(timezone.utc).isoformat())
                events.append(_event(plan, "triggered", dates[index], bar["close"]))
                break
        if trigger_index is None and len(dates) - 1 >= signal_index + execution.valid_for_days:
            expiry_date = dates[signal_index + execution.valid_for_days]
            plan.update(status="expired", exit_reason="5个交易日内未触发", updated_at=datetime.now(timezone.utc).isoformat())
            events.append(_event(plan, "expired", expiry_date, None, reason="entry_not_triggered"))
            return plan, events
    if trigger_index is None or trigger_index + 1 >= len(dates):
        return plan, events

    entry_index = trigger_index + 1
    entry_bar = _bar(series, entry_index)
    previous_close = series.close[entry_index - 1]
    entry_date = dates[entry_index]
    if entry_bar["volume"] <= 0:
        plan.update(status="cancelled", exit_reason="确认后下一交易日停牌，取消计划")
        events.append(
            _event(plan, "entry_blocked", entry_date, None, reason="suspension", price_basis="suspension")
        )
        return plan, events
    if is_sealed_limit_up(
        str(plan["symbol"]),
        str(plan["name"]),
        entry_date,
        previous_close,
        day_low=entry_bar["low"],
        day_close=entry_bar["close"],
        volume=entry_bar["volume"],
    ):
        plan.update(status="cancelled", exit_reason="确认后下一交易日封死涨停，取消计划")
        events.append(
            _event(
                plan,
                "entry_blocked",
                entry_date,
                entry_bar["close"],
                reason="sealed_limit_up",
                price_basis="sealed_limit_up",
            )
        )
        return plan, events

    notional = cost_model.account_capital * execution.initial_position_fraction
    cost = apply_execution_costs(
        entry_bar["open"],
        entry_bar["open"],
        entry_date,
        entry_date,
        notional,
        is_fund=is_fund_security(str(plan["name"])),
        cost_model=cost_model,
    )
    plan.update(
        status="open",
        entry_date=entry_date,
        raw_entry_price=entry_bar["open"],
        entry_price=cost["entry_price"],
        buy_fee_rate=cost["buy_fee_rate"],
        cost_payload={"buy": cost["buy_fees"]},
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    events.append(
        _event(
            plan,
            "opened",
            entry_date,
            float(cost["entry_price"]),
            raw_price=entry_bar["open"],
            buy_fees=cost["buy_fees"],
            price_basis="next_session_open",
            price_note="确认后次日开盘价",
        )
    )
    return plan, events


def _evaluate_exit(
    plan: dict[str, Any], series: KlineSeries, cost_model: TradingCostModel
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dates = _dates(series)
    entry_date = str(plan.get("entry_date") or "")
    if entry_date not in dates:
        return plan, []
    entry_index = dates.index(entry_date)
    latest_index = len(dates) - 1
    requested_index: int | None = None
    requested_field = "open"
    reason = ""
    theme_exit_days = int(plan.get("theme_exit_days") or PRODUCTION_PAPER_STRATEGY.theme_exit_days)
    exit_signal_date = str(plan.get("exit_signal_date") or "")
    if exit_signal_date in dates and dates.index(exit_signal_date) + 1 <= latest_index:
        requested_index = dates.index(exit_signal_date) + 1
        exit_days_text = "两" if theme_exit_days == 2 else str(theme_exit_days)
        reason = f"主线连续{exit_days_text}日退出前三"
    else:
        for index in range(entry_index, latest_index + 1):
            if series.close[index] <= float(plan["stop_price"]) and index + 1 <= latest_index:
                requested_index = index + 1
                reason = "收盘跌破失效位"
                break
        hold_index = entry_index + int(plan["max_hold_days"])
        if requested_index is None and hold_index <= latest_index:
            requested_index = hold_index
            requested_field = "close"
            reason = f"固定持有{plan['max_hold_days']}日"
    if requested_index is None:
        _mark_open_plan(plan, series, latest_index, cost_model)
        return plan, []

    delay_days = 0
    events: list[dict[str, Any]] = []
    for exit_index in range(requested_index, latest_index + 1):
        bar = _bar(series, exit_index)
        exit_date = dates[exit_index]
        blocked_reason = None
        if bar["volume"] <= 0:
            blocked_reason = "suspension"
        elif is_sealed_limit_down(
            str(plan["symbol"]),
            str(plan["name"]),
            exit_date,
            series.close[exit_index - 1],
            day_high=bar["high"],
            day_close=bar["close"],
            volume=bar["volume"],
        ):
            blocked_reason = "sealed_limit_down"
        if blocked_reason:
            delay_days += 1
            events.append(
                _event(
                    plan,
                    "exit_delayed",
                    exit_date,
                    bar["close"],
                    reason=blocked_reason,
                    price_basis=blocked_reason,
                )
            )
            continue
        field = requested_field if exit_index == requested_index else "open"
        raw_exit = bar[field]
        raw_entry = float(plan["raw_entry_price"])
        notional = cost_model.account_capital * float(plan["initial_position_fraction"])
        cost = apply_execution_costs(
            raw_entry,
            raw_exit,
            entry_date,
            exit_date,
            notional,
            is_fund=is_fund_security(str(plan["name"])),
            cost_model=cost_model,
        )
        cost_payload = dict(plan.get("cost_payload") or {})
        cost_payload["sell"] = cost["sell_fees"]
        plan.update(
            status="closed",
            exit_date=exit_date,
            raw_exit_price=raw_exit,
            exit_price=cost["exit_price"],
            sell_fee_rate=cost["sell_fee_rate"],
            net_return=cost["net_return"],
            exit_reason=reason,
            exit_delay_days=delay_days,
            cost_payload=cost_payload,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        price_basis = "next_session_open" if field == "open" else "session_close"
        events.append(
            _event(
                plan,
                "closed",
                exit_date,
                float(cost["exit_price"]),
                raw_price=raw_exit,
                net_return=cost["net_return"],
                sell_fees=cost["sell_fees"],
                reason=reason,
                price_basis=price_basis,
                price_note=(
                    "退出信号后次日开盘价"
                    if price_basis == "next_session_open"
                    else "固定持有期当日收盘价"
                ),
            )
        )
        return plan, events
    plan["exit_delay_days"] = delay_days
    _mark_open_plan(plan, series, latest_index, cost_model)
    return plan, events


def _mark_open_plan(
    plan: dict[str, Any], series: KlineSeries, index: int, cost_model: TradingCostModel
) -> None:
    dates = _dates(series)
    entry_date = str(plan.get("entry_date") or "")
    raw_entry = float(plan.get("raw_entry_price") or 0)
    raw_mark = float(series.close[index])
    if not entry_date or raw_entry <= 0 or raw_mark <= 0:
        return
    notional = cost_model.account_capital * float(plan["initial_position_fraction"])
    cost = apply_execution_costs(
        raw_entry,
        raw_mark,
        entry_date,
        dates[index],
        notional,
        is_fund=is_fund_security(str(plan["name"])),
        cost_model=cost_model,
    )
    cost_payload = dict(plan.get("cost_payload") or {})
    cost_payload["mark_sell"] = cost["sell_fees"]
    plan.update(
        mark_date=dates[index],
        mark_price=cost["exit_price"],
        sell_fee_rate=cost["sell_fee_rate"],
        net_return=cost["net_return"],
        cost_payload=cost_payload,
    )


def refresh_paper_trades(
    active_themes: set[str],
    *,
    client: TickFlowClient | None = None,
    supabase_url: str | None = None,
    supabase_publishable_key: str | None = None,
    radar_ingest_key: str | None = None,
    cost_model: TradingCostModel | None = None,
    opener: Callable[..., Any] = urlopen,
    kline_out: dict[str, KlineSeries] | None = None,
) -> PaperTradeRefreshStatus:
    url = supabase_url or os.getenv("SUPABASE_URL")
    api_key = supabase_publishable_key or os.getenv("SUPABASE_PUBLISHABLE_KEY")
    ingest_key = radar_ingest_key or os.getenv("RADAR_INGEST_KEY")
    if not url or not api_key or not ingest_key:
        return PaperTradeRefreshStatus("skipped", 0, 0, 0, "Supabase paper-trade credentials are absent")
    plans = fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_trade_plans",
        order="signal_date.asc",
        max_rows=10000,
        filters={"status": "in.(watching,triggered,open)"},
        opener=opener,
    )
    if not plans:
        return PaperTradeRefreshStatus("skipped", 0, 0, 0, "no active paper-trade plans")
    provider = client or TickFlowClient()
    klines = provider.get_klines_batch(sorted({str(plan["symbol"]) for plan in plans}), period="1d", count=120, adjust="forward")
    if kline_out is not None:
        kline_out.update(klines)
    model = cost_model or TradingCostModel()
    updated: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for original in plans:
        plan = dict(original)
        series = klines.get(str(plan["symbol"]))
        if not series or not series.timestamp:
            continue
        latest_date = _dates(series)[-1]
        theme_exit_days = int(
            plan["theme_exit_days"]
            if plan.get("theme_exit_days") is not None
            else PRODUCTION_PAPER_STRATEGY.theme_exit_days
        )
        uses_theme_exit = theme_exit_days > 0
        if str(plan.get("last_evaluated_date") or "") != latest_date:
            if uses_theme_exit:
                inactive_days = 0 if str(plan["theme"]) in active_themes else int(plan.get("inactive_theme_days") or 0) + 1
            else:
                inactive_days = 0
            plan.update(inactive_theme_days=inactive_days, last_evaluated_date=latest_date)
            if (
                uses_theme_exit
                and plan["status"] == "open"
                and inactive_days >= theme_exit_days
                and not plan.get("exit_signal_date")
            ):
                plan["exit_signal_date"] = latest_date
        if plan["status"] in {"watching", "triggered"}:
            if uses_theme_exit and int(plan.get("inactive_theme_days") or 0) >= theme_exit_days:
                exit_days_text = "两" if theme_exit_days == 2 else str(theme_exit_days)
                plan.update(status="cancelled", exit_reason=f"主线连续{exit_days_text}日退出前三，入场计划取消")
                plan_events = [_event(plan, "cancelled", latest_date, None, reason="theme_inactive")]
            else:
                plan, plan_events = _evaluate_entry(plan, series, model)
        else:
            plan, plan_events = _evaluate_exit(plan, series, model)
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()
        updated.append(plan)
        events.extend(plan_events)
    upsert_rows(url, api_key, ingest_key, "radar_trade_plans", "plan_key", updated, opener)
    upsert_rows(url, api_key, ingest_key, "radar_trade_events", "event_key", events, opener)
    return PaperTradeRefreshStatus("refreshed", len(plans), len(updated), len(events), "paper-trade ledger refreshed")
