from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable
from urllib.request import urlopen

from .execution import (
    FeeBreakdown,
    TradingCostModel,
    is_fund_security,
    is_sealed_limit_down,
    is_sealed_limit_up,
)
from .models import KlineSeries, cn_market_date_from_ms
from .paper_strategies import PRODUCTION_PAPER_STRATEGY
from .supabase_rest import call_rpc, fetch_rows, upsert_rows
from .tickflow import TickFlowClient

SHADOW_ACCOUNT_ID = "default"
SHADOW_INITIAL_CAPITAL = 100_000.0
STAR_BOARD_PREFIX = "688"


def lot_size(symbol: str) -> int:
    code = symbol.split(".", 1)[0]
    return 200 if code.startswith(STAR_BOARD_PREFIX) else 100


def _money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _session_bar(series: KlineSeries | None, as_of: str) -> tuple[dict[str, float], float] | None:
    if series is None or not series.timestamp:
        return None
    dates = _dates(series)
    if as_of not in dates:
        return None
    index = dates.index(as_of)
    previous_close = series.close[index - 1] if index > 0 else series.close[index]
    return _bar(series, index), float(previous_close)


def seed_account(as_of: str | None = None) -> dict[str, Any]:
    """Uncommitted singleton; as_of stays null until apply_shadow_day commits."""
    _ = as_of
    return {
        "account_id": SHADOW_ACCOUNT_ID,
        "cash": SHADOW_INITIAL_CAPITAL,
        "equity": SHADOW_INITIAL_CAPITAL,
        "market_value": 0.0,
        "initial_capital": SHADOW_INITIAL_CAPITAL,
        "as_of": None,
        "updated_at": _now(),
    }


def empty_snapshot(as_of: str | None = None) -> dict[str, Any]:
    account = seed_account(as_of)
    return {
        "as_of": as_of,
        "account": {
            **account,
            "pnl_total": 0.0,
            "pnl_day": 0.0,
        },
        "positions": [],
        "today_events": [],
    }


@dataclass(frozen=True)
class ShadowRefreshStatus:
    status: str
    fills: int
    blocked: int
    events_written: int
    message: str
    snapshot: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fills": self.fills,
            "blocked": self.blocked,
            "events_written": self.events_written,
            "message": self.message,
        }


_ENTRY_MODE_LABELS = {
    "breakout_close_confirm": "收盘突破确认",
    "pullback_close_reclaim": "回踩收盘站回",
}

_PRICE_NOTES = {
    "next_session_open": {
        "buy": "隔夜开盘市价挂单，按开盘价成交，再加滑点",
        "sell": "隔夜开盘卖出挂单，按开盘价成交，再减滑点",
    },
    "overnight_limit_open": {
        "buy": "隔夜限价挂单，开盘不高于建议购买价，按开盘价成交，再加滑点",
        "sell": "隔夜限价挂单，开盘优于限价，按开盘价成交，再减滑点",
    },
    "overnight_limit": {
        "buy": "隔夜限价挂单，开盘高于建议购买价，按建议购买价限价成交，再加滑点",
        "sell": "隔夜限价挂单，按建议卖出价限价成交，再减滑点",
    },
    "zone_high_limit": {
        "buy": "隔夜限价挂单，开盘高于建议购买价，按建议购买价限价成交，再加滑点",
        "sell": "隔夜限价挂单，按建议卖出价限价成交，再减滑点",
    },
    "session_open": {
        "buy": "纸面未提供成交价，改用当日开盘价，再加滑点",
        "sell": "纸面未提供成交价，改用当日开盘价，再减滑点",
    },
    "paper_raw_price": {
        "buy": "使用纸面事件 raw_price（与当日开盘价不同），再加滑点",
        "sell": "使用纸面事件 raw_price（与当日开盘价不同），再减滑点",
    },
    "session_close": {
        "buy": "按当日收盘价成交，再加滑点",
        "sell": "按当日收盘价成交（固定持有期），再减滑点",
    },
    "missing_bar": "缺当日K线，未按开盘价成交",
    "sealed_limit_up": "当日封死涨停，未按开盘价成交",
    "sealed_limit_down": "当日封死跌停，未按开盘价成交",
    "suspension": "当日停牌，未按开盘价成交",
    "t1": "T+1 当日买入不可卖，未成交",
    "insufficient_cash": "现金不足，未成交",
    "expired_no_zone_touch": "隔夜限价挂单有效期内未触及建议购买价，未成交",
    "overnight_limit_not_tagged": "隔夜限价挂单有效期内未触及建议购买价，未成交",
}


def _present(value: Any) -> bool:
    return value not in (None, "")


def _paper_intent_fields(plan: dict[str, Any], payload: dict[str, Any], event_type: str) -> dict[str, Any]:
    working = (plan.get("cost_payload") or {}).get("working_order")
    working = working if isinstance(working, dict) else {}
    fields = {
        "theme": plan.get("theme") or payload.get("theme"),
        "status": plan.get("status"),
        "entry_mode": plan.get("entry_mode") or payload.get("entry_mode"),
        "entry_zone_low": plan.get("entry_zone_low"),
        "entry_zone_high": plan.get("entry_zone_high"),
        "confirm_price": plan.get("confirm_price"),
        "stop_price": plan.get("stop_price"),
        "trigger_date": plan.get("trigger_date"),
        "entry_date": plan.get("entry_date"),
        "exit_reason": plan.get("exit_reason"),
        "paper_event_type": event_type,
        "paper_price_basis": payload.get("price_basis"),
        "reason": payload.get("reason"),
        "suggested_buy_price": payload.get("suggested_buy_price") or working.get("suggested_buy_price"),
        "working_order_type": payload.get("working_order_type") or working.get("working_order_type"),
        "working_order_note": payload.get("working_order_note") or working.get("working_order_note"),
    }
    return {key: value for key, value in fields.items() if _present(value)}


def _resolve_price_basis(
    *,
    intent: dict[str, Any],
    session_open: float | None,
    session_close: float | None,
    raw_price: float | None,
    used_session_fallback: bool,
    branch: str,
) -> str:
    if branch != "filled":
        return branch
    paper_basis = intent.get("paper_price_basis")
    if _present(paper_basis):
        return str(paper_basis)
    if used_session_fallback:
        return "session_open"
    paper_event = str(intent.get("paper_event_type") or "")
    if paper_event == "opened":
        return "next_session_open"
    if raw_price is not None and session_open is not None and abs(raw_price - session_open) < 1e-9:
        return "next_session_open"
    if raw_price is not None and session_close is not None and abs(raw_price - session_close) < 1e-9:
        return "session_close"
    if _present(intent.get("raw_price")):
        return "paper_raw_price"
    return "session_open"


def _price_note(price_basis: str, *, side: str) -> str:
    mapped = _PRICE_NOTES.get(price_basis)
    if isinstance(mapped, dict):
        return str(mapped.get(side) or mapped.get("buy") or price_basis)
    if isinstance(mapped, str):
        return mapped
    return f"价格分支：{price_basis}"


def _reason_note(*, side: str, intent: dict[str, Any], extra_reason: str | None = None) -> tuple[str, list[str]]:
    parts: list[str] = []
    missing: list[str] = []
    theme = intent.get("theme")
    if _present(theme):
        parts.append(f"主线{theme}")
    else:
        missing.append("theme")
    if side == "buy":
        event_type = intent.get("paper_event_type")
        basis = str(intent.get("paper_price_basis") or "")
        reason = str(intent.get("reason") or extra_reason or "")
        if event_type == "opened":
            if basis in {"overnight_limit", "zone_high_limit"} or reason in {"overnight_limit", "pullback_into_zone"}:
                parts.append("隔夜限价挂单触及建议购买价买入")
            elif basis == "overnight_limit_open" or reason == "price_improvement":
                parts.append("隔夜限价挂单，开盘优于建议购买价买入")
            elif str(intent.get("working_order_type") or "") == "overnight_limit":
                parts.append("隔夜限价挂单买入")
            else:
                parts.append("隔夜开盘市价挂单买入")
        elif event_type == "entry_blocked":
            parts.append("纸面入场阻断，未开仓")
        elif event_type == "expired":
            parts.append("有效期内隔夜限价未成交，未开仓")
        else:
            missing.append("paper_event_type")
        if _present(intent.get("suggested_buy_price")):
            parts.append(f"建议购买价{intent['suggested_buy_price']}")
        elif _present(intent.get("working_order_note")):
            parts.append(str(intent["working_order_note"]))
        if _present(intent.get("status")):
            parts.append(f"计划状态{intent['status']}")
        else:
            missing.append("status")
        entry_mode = intent.get("entry_mode")
        if _present(entry_mode):
            parts.append(f"入场模式{_ENTRY_MODE_LABELS.get(str(entry_mode), entry_mode)}")
        else:
            missing.append("entry_mode")
        if _present(intent.get("confirm_price")):
            parts.append(f"确认价{intent['confirm_price']}")
        else:
            missing.append("confirm_price")
        low, high = intent.get("entry_zone_low"), intent.get("entry_zone_high")
        if _present(low) and _present(high):
            parts.append(f"买入区间{low}-{high}")
        else:
            if not _present(low):
                missing.append("entry_zone_low")
            if not _present(high):
                missing.append("entry_zone_high")
        if _present(intent.get("trigger_date")):
            parts.append(f"确认日{intent['trigger_date']}")
    else:
        exit_reason = intent.get("exit_reason") or extra_reason or intent.get("reason")
        if _present(exit_reason):
            parts.append(str(exit_reason))
        else:
            missing.extend(["exit_reason", "payload.reason"])
        if _present(intent.get("stop_price")):
            parts.append(f"失效位{intent['stop_price']}")
    note = "；".join(parts) if parts else "成交理由字段缺失，无法还原"
    if missing:
        note = f"{note}。缺失字段：{', '.join(missing)}"
    return note, missing


def _execution_fields(
    *,
    side: str,
    intent: dict[str, Any],
    session_open: float | None,
    session_close: float | None = None,
    raw_price: float | None = None,
    fill_price: float | None = None,
    qty: int | None = None,
    fees: dict[str, Any] | None = None,
    notional: float | None = None,
    debit: float | None = None,
    proceeds: float | None = None,
    slippage_rate: float,
    used_session_fallback: bool,
    branch: str,
    extra_reason: str | None = None,
) -> dict[str, Any]:
    reason_note, missing = _reason_note(side=side, intent=intent, extra_reason=extra_reason)
    price_basis = _resolve_price_basis(
        intent=intent,
        session_open=session_open,
        session_close=session_close,
        raw_price=raw_price,
        used_session_fallback=used_session_fallback,
        branch=branch,
    )
    price_note = _price_note(price_basis, side=side)
    fill_bits: list[str] = []
    if qty is not None and fill_price is not None:
        fill_bits.append(f"{qty}股 @ {fill_price:.4f}")
    if fees and fees.get("total") is not None:
        fill_bits.append(f"费用{_money(float(fees['total']))}")
    if notional is not None:
        fill_bits.append(f"成交额{_money(notional)}")
    if debit is not None:
        fill_bits.append(f"扣款{_money(debit)}")
    if proceeds is not None:
        fill_bits.append(f"入账{_money(proceeds)}")
    fill_text = "，".join(fill_bits) if fill_bits else "未成交"
    fields: dict[str, Any] = {
        "theme": intent.get("theme"),
        "status": intent.get("status"),
        "entry_mode": intent.get("entry_mode"),
        "confirm_price": intent.get("confirm_price"),
        "entry_zone_low": intent.get("entry_zone_low"),
        "entry_zone_high": intent.get("entry_zone_high"),
        "stop_price": intent.get("stop_price"),
        "trigger_date": intent.get("trigger_date"),
        "suggested_buy_price": intent.get("suggested_buy_price"),
        "working_order_type": intent.get("working_order_type"),
        "working_order_note": intent.get("working_order_note"),
        "reason_note": reason_note,
        "price_basis": price_basis,
        "slippage_rate": slippage_rate,
        "price_note": price_note,
        "execution_note": f"成交理由：{reason_note}\n成交价：{fill_text}\n价格怎么选的：{price_note}",
        "missing_fields": missing,
    }
    if _present(intent.get("exit_reason") or extra_reason or intent.get("reason")):
        fields["exit_reason"] = intent.get("exit_reason") or extra_reason or intent.get("reason")
    if session_open is not None:
        fields["session_open"] = _money(session_open)
    if fill_price is not None:
        fields["fill_price"] = fill_price
    return {key: value for key, value in fields.items() if value not in (None, "", [])}


def _event(
    as_of: str,
    event_type: str,
    *,
    symbol: str | None = None,
    price: float | None = None,
    qty: int | None = None,
    fees: dict[str, Any] | None = None,
    **payload: Any,
) -> dict[str, Any]:
    suffix = symbol or SHADOW_ACCOUNT_ID
    return {
        "event_key": f"{as_of}:{event_type}:{suffix}",
        "account_id": SHADOW_ACCOUNT_ID,
        "as_of": as_of,
        "symbol": symbol,
        "event_type": event_type,
        "price": price,
        "qty": qty,
        "fees": fees or {},
        "payload": payload,
        "created_at": _now(),
    }


def _affordable_shares(
    symbol: str,
    fill_price: float,
    cash: float,
    equity: float,
    initial_fraction: float,
    max_fraction: float,
    trade_date: str,
    *,
    is_fund: bool,
    cost_model: TradingCostModel,
) -> tuple[int, FeeBreakdown | None]:
    lot = lot_size(symbol)
    if fill_price <= 0 or lot <= 0 or cash <= 0 or equity <= 0:
        return 0, None
    cap = min(cash, equity * initial_fraction, equity * max_fraction)
    max_lots = int(cap // (fill_price * lot))
    for lots in range(max_lots, 0, -1):
        shares = lots * lot
        notional = _money(shares * fill_price)
        fees = cost_model.fee_breakdown(notional, trade_date, side="buy", is_fund=is_fund)
        if notional + fees.total <= cash + 1e-9:
            return shares, fees
    return 0, None


def _unlock_t1(positions: list[dict[str, Any]], as_of: str) -> None:
    for position in positions:
        if str(position.get("buy_dt") or "") < as_of:
            position["sellable_shares"] = int(position["shares"])


def _mark_positions(
    positions: list[dict[str, Any]],
    klines: dict[str, KlineSeries],
    as_of: str,
) -> float:
    market_value = 0.0
    remaining: list[dict[str, Any]] = []
    for position in positions:
        session = _session_bar(klines.get(str(position["symbol"])), as_of)
        mark = float(session[0]["close"]) if session else float(position.get("last_mark") or 0)
        if mark > 0:
            position["last_mark"] = _money(mark)
        market_value += int(position["shares"]) * float(position.get("last_mark") or 0)
        remaining.append(position)
    positions[:] = remaining
    return _money(market_value)


def _apply_sells(
    intents: list[dict[str, Any]],
    *,
    as_of: str,
    klines: dict[str, KlineSeries],
    model: TradingCostModel,
    state: dict[str, Any],
    held: list[dict[str, Any]],
    by_symbol: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    for intent in intents:
        symbol = str(intent["symbol"])
        position = by_symbol.get(symbol)
        if position is None:
            continue
        session = _session_bar(klines.get(symbol), as_of)
        sell_reason = intent.get("reason") or position.get("exit_pending_reason")
        if session is None:
            events.append(
                _event(
                    as_of,
                    "exit_delayed",
                    symbol=symbol,
                    reason="missing_bar",
                    **_execution_fields(
                        side="sell",
                        intent=intent,
                        session_open=None,
                        raw_price=intent.get("raw_price"),
                        slippage_rate=model.slippage_rate,
                        used_session_fallback=not _present(intent.get("raw_price")),
                        branch="missing_bar",
                        extra_reason=sell_reason,
                    ),
                )
            )
            position["exit_pending_reason"] = "missing_bar"
            continue
        bar, previous_close = session
        name = str(position.get("name") or intent.get("name") or symbol)
        if bar["volume"] <= 0:
            events.append(
                _event(
                    as_of,
                    "exit_delayed",
                    symbol=symbol,
                    price=bar["close"],
                    reason="suspension",
                    **_execution_fields(
                        side="sell",
                        intent=intent,
                        session_open=bar["open"],
                        session_close=bar["close"],
                        raw_price=intent.get("raw_price"),
                        slippage_rate=model.slippage_rate,
                        used_session_fallback=not _present(intent.get("raw_price")),
                        branch="suspension",
                        extra_reason=sell_reason,
                    ),
                )
            )
            position["exit_pending_reason"] = "suspension"
            continue
        if is_sealed_limit_down(
            symbol,
            name,
            as_of,
            previous_close,
            day_high=bar["high"],
            day_close=bar["close"],
            volume=bar["volume"],
        ):
            events.append(
                _event(
                    as_of,
                    "exit_delayed",
                    symbol=symbol,
                    price=bar["close"],
                    reason="sealed_limit_down",
                    **_execution_fields(
                        side="sell",
                        intent=intent,
                        session_open=bar["open"],
                        session_close=bar["close"],
                        raw_price=intent.get("raw_price"),
                        slippage_rate=model.slippage_rate,
                        used_session_fallback=not _present(intent.get("raw_price")),
                        branch="sealed_limit_down",
                        extra_reason=sell_reason,
                    ),
                )
            )
            position["exit_pending_reason"] = "sealed_limit_down"
            continue
        sellable = int(position.get("sellable_shares") or 0)
        if sellable <= 0:
            events.append(
                _event(
                    as_of,
                    "skip_t1",
                    symbol=symbol,
                    qty=int(position["shares"]),
                    reason="t1",
                    **_execution_fields(
                        side="sell",
                        intent=intent,
                        session_open=bar["open"],
                        session_close=bar["close"],
                        raw_price=intent.get("raw_price"),
                        qty=int(position["shares"]),
                        slippage_rate=model.slippage_rate,
                        used_session_fallback=not _present(intent.get("raw_price")),
                        branch="t1",
                        extra_reason=sell_reason,
                    ),
                )
            )
            position["exit_pending_reason"] = "t1"
            continue
        used_session_fallback = not _present(intent.get("raw_price"))
        raw_price = float(intent.get("raw_price") or bar["open"])
        fill_price = raw_price * (1 - model.slippage_rate)
        notional = _money(sellable * fill_price)
        fund = is_fund_security(name)
        fees = model.fee_breakdown(notional, as_of, side="sell", is_fund=fund)
        proceeds = _money(notional - fees.total)
        state["cash"] = _money(float(state["cash"]) + proceeds)
        events.append(
            _event(
                as_of,
                "fill_sell",
                symbol=symbol,
                price=_money(fill_price),
                qty=sellable,
                fees=fees.to_dict(),
                raw_price=raw_price,
                notional=notional,
                proceeds=proceeds,
                reason=sell_reason,
                **_execution_fields(
                    side="sell",
                    intent=intent,
                    session_open=bar["open"],
                    session_close=bar["close"],
                    raw_price=raw_price,
                    fill_price=fill_price,
                    qty=sellable,
                    fees=fees.to_dict(),
                    notional=notional,
                    proceeds=proceeds,
                    slippage_rate=model.slippage_rate,
                    used_session_fallback=used_session_fallback,
                    branch="filled",
                    extra_reason=sell_reason,
                ),
            )
        )
        held[:] = [item for item in held if item["symbol"] != symbol]
        by_symbol.pop(symbol, None)


def execute_shadow_day(
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    *,
    as_of: str,
    klines: dict[str, KlineSeries],
    buy_intents: list[dict[str, Any]],
    sell_intents: list[dict[str, Any]],
    cost_model: TradingCostModel | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply one cash-book session: T+1 unlock, sells, buys, then mark."""
    model = cost_model or TradingCostModel(account_capital=SHADOW_INITIAL_CAPITAL)
    state = dict(account)
    held = [dict(item) for item in positions]
    _unlock_t1(held, as_of)
    by_symbol = {str(item["symbol"]): item for item in held}
    events: list[dict[str, Any]] = []
    held_at_start = set(by_symbol)
    _apply_sells(
        sell_intents,
        as_of=as_of,
        klines=klines,
        model=model,
        state=state,
        held=held,
        by_symbol=by_symbol,
        events=events,
    )

    equity_for_buy = _money(float(state["cash"]) + sum(int(p["shares"]) * float(p.get("last_mark") or 0) for p in held))
    for intent in buy_intents:
        symbol = str(intent["symbol"])
        if symbol in by_symbol:
            continue
        paper_event = str(intent.get("paper_event_type") or "")
        if paper_event in {"entry_blocked", "expired"}:
            session = _session_bar(klines.get(symbol), as_of)
            bar = session[0] if session else None
            events.append(
                _event(
                    as_of,
                    paper_event,
                    symbol=symbol,
                    price=bar["close"] if bar else None,
                    reason=intent.get("reason") or paper_event,
                    **_execution_fields(
                        side="buy",
                        intent=intent,
                        session_open=bar["open"] if bar else None,
                        session_close=bar["close"] if bar else None,
                        raw_price=intent.get("raw_price"),
                        slippage_rate=model.slippage_rate,
                        used_session_fallback=not _present(intent.get("raw_price")),
                        branch=str(intent.get("paper_price_basis") or intent.get("reason") or paper_event),
                    ),
                )
            )
            continue
        session = _session_bar(klines.get(symbol), as_of)
        if session is None:
            events.append(
                _event(
                    as_of,
                    "entry_blocked",
                    symbol=symbol,
                    reason="missing_bar",
                    **_execution_fields(
                        side="buy",
                        intent=intent,
                        session_open=None,
                        raw_price=intent.get("raw_price"),
                        slippage_rate=model.slippage_rate,
                        used_session_fallback=not _present(intent.get("raw_price")),
                        branch="missing_bar",
                    ),
                )
            )
            continue
        bar, previous_close = session
        name = str(intent.get("name") or symbol)
        if bar["volume"] <= 0:
            events.append(
                _event(
                    as_of,
                    "entry_blocked",
                    symbol=symbol,
                    price=bar["close"],
                    reason="suspension",
                    **_execution_fields(
                        side="buy",
                        intent=intent,
                        session_open=bar["open"],
                        session_close=bar["close"],
                        raw_price=intent.get("raw_price"),
                        slippage_rate=model.slippage_rate,
                        used_session_fallback=not _present(intent.get("raw_price")),
                        branch="suspension",
                    ),
                )
            )
            continue
        if is_sealed_limit_up(
            symbol,
            name,
            as_of,
            previous_close,
            day_low=bar["low"],
            day_close=bar["close"],
            volume=bar["volume"],
        ):
            events.append(
                _event(
                    as_of,
                    "entry_blocked",
                    symbol=symbol,
                    price=bar["close"],
                    reason="sealed_limit_up",
                    **_execution_fields(
                        side="buy",
                        intent=intent,
                        session_open=bar["open"],
                        session_close=bar["close"],
                        raw_price=intent.get("raw_price"),
                        slippage_rate=model.slippage_rate,
                        used_session_fallback=not _present(intent.get("raw_price")),
                        branch="sealed_limit_up",
                    ),
                )
            )
            continue
        used_session_fallback = not _present(intent.get("raw_price"))
        raw_price = float(intent.get("raw_price") or bar["open"])
        fill_price = raw_price * (1 + model.slippage_rate)
        fund = is_fund_security(name)
        shares, fees = _affordable_shares(
            symbol,
            fill_price,
            float(state["cash"]),
            equity_for_buy,
            float(intent.get("initial_position_fraction") or (1 / 12)),
            float(intent.get("max_position_fraction") or 0.25),
            as_of,
            is_fund=fund,
            cost_model=model,
        )
        if shares <= 0 or fees is None:
            events.append(
                _event(
                    as_of,
                    "skip_insufficient_cash",
                    symbol=symbol,
                    price=_money(fill_price),
                    reason="insufficient_cash",
                    cash=_money(float(state["cash"])),
                    **_execution_fields(
                        side="buy",
                        intent=intent,
                        session_open=bar["open"],
                        session_close=bar["close"],
                        raw_price=raw_price,
                        fill_price=fill_price,
                        slippage_rate=model.slippage_rate,
                        used_session_fallback=used_session_fallback,
                        branch="insufficient_cash",
                    ),
                )
            )
            continue
        notional = _money(shares * fill_price)
        debit = _money(notional + fees.total)
        state["cash"] = _money(float(state["cash"]) - debit)
        avg_cost = _money(debit / shares)
        position = {
            "account_id": SHADOW_ACCOUNT_ID,
            "symbol": symbol,
            "name": name,
            "shares": shares,
            "sellable_shares": 0,
            "avg_cost": avg_cost,
            "buy_dt": as_of,
            "last_mark": _money(bar["close"]),
            "opened_at": _now(),
            "exit_pending_reason": None,
        }
        held.append(position)
        by_symbol[symbol] = position
        equity_for_buy = _money(float(state["cash"]) + sum(int(p["shares"]) * float(p.get("last_mark") or 0) for p in held))
        events.append(
            _event(
                as_of,
                "fill_buy",
                symbol=symbol,
                price=_money(fill_price),
                qty=shares,
                fees=fees.to_dict(),
                raw_price=raw_price,
                notional=notional,
                debit=debit,
                avg_cost=avg_cost,
                name=name,
                **_execution_fields(
                    side="buy",
                    intent=intent,
                    session_open=bar["open"],
                    session_close=bar["close"],
                    raw_price=raw_price,
                    fill_price=fill_price,
                    qty=shares,
                    fees=fees.to_dict(),
                    notional=notional,
                    debit=debit,
                    slippage_rate=model.slippage_rate,
                    used_session_fallback=used_session_fallback,
                    branch="filled",
                ),
            )
        )

    _apply_sells(
        [intent for intent in sell_intents if str(intent["symbol"]) not in held_at_start],
        as_of=as_of,
        klines=klines,
        model=model,
        state=state,
        held=held,
        by_symbol=by_symbol,
        events=events,
    )

    market_value = _mark_positions(held, klines, as_of)
    cash = _money(float(state["cash"]))
    equity = _money(cash + market_value)
    initial = float(state.get("initial_capital") or SHADOW_INITIAL_CAPITAL)
    state.update(
        cash=cash,
        market_value=market_value,
        equity=equity,
        as_of=as_of,
        updated_at=_now(),
        initial_capital=initial,
        account_id=SHADOW_ACCOUNT_ID,
    )
    events.append(
        _event(
            as_of,
            "mark",
            cash=cash,
            market_value=market_value,
            equity=equity,
            pnl_total=_money(equity - initial),
        )
    )
    return state, held, events


def _production_event(row: dict[str, Any]) -> bool:
    version = str(row.get("strategy_version") or PRODUCTION_PAPER_STRATEGY.version)
    return version == PRODUCTION_PAPER_STRATEGY.version


def _intents_from_paper(
    events: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    positions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plans_by_symbol = {str(row["symbol"]): row for row in plans if row.get("symbol")}
    buy_intents: list[dict[str, Any]] = []
    sell_intents: list[dict[str, Any]] = []
    sell_symbols: set[str] = set()
    for row in events:
        if not _production_event(row):
            continue
        event_type = str(row.get("event_type") or "")
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        plan = plans_by_symbol.get(symbol, {})
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if event_type in {"opened", "entry_blocked", "expired"}:
            buy_intents.append(
                {
                    "symbol": symbol,
                    "name": plan.get("name") or payload.get("name") or symbol,
                    "raw_price": payload.get("raw_price") or row.get("price"),
                    "initial_position_fraction": plan.get("initial_position_fraction") or (1 / 12),
                    "max_position_fraction": plan.get("max_position_fraction") or 0.25,
                    **_paper_intent_fields(plan, payload, event_type),
                }
            )
        elif event_type in {"closed", "exit_delayed"}:
            sell_intents.append(
                {
                    "symbol": symbol,
                    "name": plan.get("name") or symbol,
                    "raw_price": payload.get("raw_price") or row.get("price"),
                    "reason": payload.get("reason") or event_type,
                    **_paper_intent_fields(plan, payload, event_type),
                }
            )
            sell_symbols.add(symbol)
    for position in positions:
        symbol = str(position["symbol"])
        reason = position.get("exit_pending_reason")
        if reason and symbol not in sell_symbols:
            sell_intents.append({"symbol": symbol, "name": position.get("name"), "reason": reason})
            sell_symbols.add(symbol)
    return buy_intents, sell_intents


def _snapshot(account: dict[str, Any], positions: list[dict[str, Any]], events: list[dict[str, Any]], pnl_day: float) -> dict[str, Any]:
    initial = float(account.get("initial_capital") or SHADOW_INITIAL_CAPITAL)
    equity = float(account.get("equity") or 0)
    return {
        "as_of": account.get("as_of"),
        "account": {
            **account,
            "pnl_total": _money(equity - initial),
            "pnl_day": _money(pnl_day),
        },
        "positions": positions,
        "today_events": events,
    }


def _committed_as_of(account: dict[str, Any]) -> str:
    value = account.get("as_of")
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in {"", "None", "null"} else text


def _session_committed(book_as_of: str, as_of: str) -> bool:
    return bool(book_as_of) and book_as_of == as_of


def _commit_shadow_day(
    url: str,
    api_key: str,
    ingest_key: str | None,
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    events: list[dict[str, Any]],
    nav: dict[str, Any],
    opener: Callable[..., Any],
) -> None:
    """Write the day's book in one database transaction."""
    call_rpc(
        url,
        api_key,
        ingest_key,
        "apply_shadow_day",
        {
            "p_account": account,
            "p_positions": positions,
            "p_events": events,
            "p_nav": nav,
        },
        opener,
    )


def refresh_shadow_account(
    *,
    as_of: str | None,
    client: TickFlowClient | None = None,
    klines: dict[str, KlineSeries] | None = None,
    supabase_url: str | None = None,
    supabase_publishable_key: str | None = None,
    radar_ingest_key: str | None = None,
    cost_model: TradingCostModel | None = None,
    opener: Callable[..., Any] = urlopen,
) -> ShadowRefreshStatus:
    url = supabase_url or os.getenv("SUPABASE_URL")
    api_key = supabase_publishable_key or os.getenv("SUPABASE_PUBLISHABLE_KEY")
    ingest_key = radar_ingest_key or os.getenv("RADAR_INGEST_KEY")
    if not as_of:
        return ShadowRefreshStatus("skipped", 0, 0, 0, "shadow as_of date is absent", empty_snapshot(None))
    if not url or not api_key or not ingest_key:
        return ShadowRefreshStatus(
            "skipped",
            0,
            0,
            0,
            "Supabase shadow-account credentials are absent",
            empty_snapshot(as_of),
        )

    accounts = fetch_rows(
        url,
        api_key,
        ingest_key,
        "shadow_account",
        order="account_id.asc",
        max_rows=1,
        filters={"account_id": f"eq.{SHADOW_ACCOUNT_ID}"},
        opener=opener,
    )
    account = dict(accounts[0]) if accounts else seed_account()
    if not accounts:
        upsert_rows(url, api_key, ingest_key, "shadow_account", "account_id", [account], opener)

    positions = fetch_rows(
        url,
        api_key,
        ingest_key,
        "shadow_positions",
        order="symbol.asc",
        max_rows=100,
        filters={"account_id": f"eq.{SHADOW_ACCOUNT_ID}"},
        opener=opener,
    )
    book_as_of = _committed_as_of(account)
    if book_as_of and book_as_of > as_of:
        snapshot = _snapshot(account, [dict(item) for item in positions], [], 0.0)
        return ShadowRefreshStatus(
            "skipped",
            0,
            0,
            0,
            f"refuse historical replay: live book as_of {book_as_of} is after {as_of}",
            snapshot,
        )
    if _session_committed(book_as_of, as_of):
        today_events = fetch_rows(
            url,
            api_key,
            ingest_key,
            "shadow_events",
            order="created_at.asc",
            max_rows=1000,
            filters={"as_of": f"eq.{as_of}", "account_id": f"eq.{SHADOW_ACCOUNT_ID}"},
            opener=opener,
        )
        nav_rows = fetch_rows(
            url,
            api_key,
            ingest_key,
            "shadow_nav_daily",
            order="as_of.desc",
            max_rows=1,
            filters={"as_of": f"eq.{as_of}"},
            opener=opener,
        )
        pnl_day = float(nav_rows[0]["pnl_day"]) if nav_rows else 0.0
        fills = sum(1 for item in today_events if item.get("event_type") in {"fill_buy", "fill_sell"})
        blocked = sum(
            1
            for item in today_events
            if item.get("event_type")
            in {"entry_blocked", "expired", "exit_delayed", "skip_insufficient_cash", "skip_t1"}
        )
        snapshot = _snapshot(account, [dict(item) for item in positions], today_events, pnl_day)
        return ShadowRefreshStatus(
            "refreshed",
            fills,
            blocked,
            0,
            "shadow cash ledger already committed",
            snapshot,
        )

    paper_events = fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_trade_events",
        order="created_at.asc",
        max_rows=1000,
        filters={
            "event_date": f"eq.{as_of}",
            "strategy_version": f"eq.{PRODUCTION_PAPER_STRATEGY.version}",
        },
        opener=opener,
    )
    paper_plans = fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_trade_plans",
        order="signal_date.asc",
        max_rows=1000,
        filters={
            "last_evaluated_date": f"eq.{as_of}",
            "strategy_version": f"eq.{PRODUCTION_PAPER_STRATEGY.version}",
        },
        opener=opener,
    )
    buy_intents, sell_intents = _intents_from_paper(paper_events, paper_plans, positions)
    needed = {str(item["symbol"]) for item in positions}
    needed.update(str(item["symbol"]) for item in buy_intents)
    needed.update(str(item["symbol"]) for item in sell_intents)
    series_map = dict(klines or {})
    missing = sorted(symbol for symbol in needed if symbol not in series_map)
    if missing:
        provider = client or TickFlowClient()
        series_map.update(provider.get_klines_batch(missing, period="1d", count=120, adjust="forward"))

    model = cost_model or TradingCostModel(account_capital=SHADOW_INITIAL_CAPITAL)
    next_account, next_positions, events = execute_shadow_day(
        account,
        positions,
        as_of=as_of,
        klines=series_map,
        buy_intents=buy_intents,
        sell_intents=sell_intents,
        cost_model=model,
    )

    nav_rows = fetch_rows(
        url,
        api_key,
        ingest_key,
        "shadow_nav_daily",
        order="as_of.desc",
        max_rows=8,
        opener=opener,
    )
    previous_equity = SHADOW_INITIAL_CAPITAL
    for row in nav_rows:
        if str(row.get("as_of") or "") < as_of:
            previous_equity = float(row.get("equity") or SHADOW_INITIAL_CAPITAL)
            break
    pnl_day = _money(float(next_account["equity"]) - previous_equity)
    nav = {
        "as_of": as_of,
        "cash": next_account["cash"],
        "market_value": next_account["market_value"],
        "equity": next_account["equity"],
        "pnl_day": pnl_day,
        "pnl_total": _money(float(next_account["equity"]) - float(next_account["initial_capital"])),
    }
    _commit_shadow_day(url, api_key, ingest_key, next_account, next_positions, events, nav, opener)

    fills = sum(1 for item in events if item["event_type"] in {"fill_buy", "fill_sell"})
    blocked = sum(
        1
        for item in events
        if item["event_type"] in {"entry_blocked", "expired", "exit_delayed", "skip_insufficient_cash", "skip_t1"}
    )
    snapshot = _snapshot(next_account, next_positions, events, pnl_day)
    return ShadowRefreshStatus("refreshed", fills, blocked, len(events), "shadow cash ledger refreshed", snapshot)
