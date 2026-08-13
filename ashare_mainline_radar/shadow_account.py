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
from .supabase_rest import delete_rows, fetch_rows, quoted_in, upsert_rows
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
    return {
        "account_id": SHADOW_ACCOUNT_ID,
        "cash": SHADOW_INITIAL_CAPITAL,
        "equity": SHADOW_INITIAL_CAPITAL,
        "market_value": 0.0,
        "initial_capital": SHADOW_INITIAL_CAPITAL,
        "as_of": as_of,
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
        if session is None:
            events.append(_event(as_of, "exit_delayed", symbol=symbol, reason="missing_bar"))
            position["exit_pending_reason"] = "missing_bar"
            continue
        bar, previous_close = session
        name = str(position.get("name") or intent.get("name") or symbol)
        if bar["volume"] <= 0:
            events.append(
                _event(as_of, "exit_delayed", symbol=symbol, price=bar["close"], reason="suspension")
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
                _event(as_of, "exit_delayed", symbol=symbol, price=bar["close"], reason="sealed_limit_down")
            )
            position["exit_pending_reason"] = "sealed_limit_down"
            continue
        sellable = int(position.get("sellable_shares") or 0)
        if sellable <= 0:
            events.append(_event(as_of, "skip_t1", symbol=symbol, qty=int(position["shares"]), reason="t1"))
            position["exit_pending_reason"] = "t1"
            continue
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
                reason=intent.get("reason") or position.get("exit_pending_reason"),
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
        session = _session_bar(klines.get(symbol), as_of)
        if session is None:
            events.append(_event(as_of, "entry_blocked", symbol=symbol, reason="missing_bar"))
            continue
        bar, previous_close = session
        name = str(intent.get("name") or symbol)
        if bar["volume"] <= 0:
            events.append(_event(as_of, "entry_blocked", symbol=symbol, price=bar["close"], reason="suspension"))
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
                _event(as_of, "entry_blocked", symbol=symbol, price=bar["close"], reason="sealed_limit_up")
            )
            continue
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
        if event_type == "opened":
            buy_intents.append(
                {
                    "symbol": symbol,
                    "name": plan.get("name") or payload.get("name") or symbol,
                    "raw_price": payload.get("raw_price") or row.get("price"),
                    "initial_position_fraction": plan.get("initial_position_fraction") or (1 / 12),
                    "max_position_fraction": plan.get("max_position_fraction") or 0.25,
                }
            )
        elif event_type == "entry_blocked":
            buy_intents.append(
                {
                    "symbol": symbol,
                    "name": plan.get("name") or symbol,
                    "raw_price": payload.get("raw_price") or row.get("price"),
                    "initial_position_fraction": plan.get("initial_position_fraction") or (1 / 12),
                    "max_position_fraction": plan.get("max_position_fraction") or 0.25,
                }
            )
        elif event_type in {"closed", "exit_delayed"}:
            sell_intents.append(
                {
                    "symbol": symbol,
                    "name": plan.get("name") or symbol,
                    "raw_price": payload.get("raw_price") or row.get("price"),
                    "reason": payload.get("reason") or event_type,
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


def _fill_symbols(events: list[dict[str, Any]], event_type: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for row in events:
        if str(row.get("event_type") or "") != event_type:
            continue
        symbol = str(row.get("symbol") or "")
        if symbol:
            found[symbol] = row
    return found


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else {}


def _reconcile_recorded_fills(
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    applied_sells: dict[str, dict[str, Any]],
    applied_buys: dict[str, dict[str, Any]],
    as_of: str,
) -> list[dict[str, Any]]:
    """Apply already-persisted fills to cash when the account row is still on a prior day."""
    book_as_of = str(account.get("as_of") or "")
    if book_as_of < as_of:
        cash = float(account.get("cash") or 0)
        for fill in applied_sells.values():
            cash = _money(cash + float(_payload(fill).get("proceeds") or 0))
        for fill in applied_buys.values():
            cash = _money(cash - float(_payload(fill).get("debit") or 0))
        account["cash"] = cash
    return [item for item in positions if str(item["symbol"]) not in applied_sells]


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
    account = dict(accounts[0]) if accounts else seed_account(as_of)
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
    book_as_of = str(account.get("as_of") or "")
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
    ledger_events = fetch_rows(
        url,
        api_key,
        ingest_key,
        "shadow_events",
        order="created_at.asc",
        max_rows=1000,
        filters={"as_of": f"eq.{as_of}", "account_id": f"eq.{SHADOW_ACCOUNT_ID}"},
        opener=opener,
    )
    applied_sells = _fill_symbols(ledger_events, "fill_sell")
    applied_buys = _fill_symbols(ledger_events, "fill_buy")
    positions = _reconcile_recorded_fills(
        account,
        [dict(item) for item in positions],
        applied_sells,
        applied_buys,
        as_of,
    )
    buy_intents, sell_intents = _intents_from_paper(paper_events, paper_plans, positions)
    buy_intents = [item for item in buy_intents if str(item["symbol"]) not in applied_buys]
    sell_intents = [item for item in sell_intents if str(item["symbol"]) not in applied_sells]
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

    opened_before = {str(item["symbol"]) for item in positions} | set(applied_sells)
    opened_after = {str(item["symbol"]) for item in next_positions}
    sold = sorted(opened_before - opened_after)
    fill_events = [item for item in events if item["event_type"] in {"fill_buy", "fill_sell"}]
    other_events = [item for item in events if item["event_type"] not in {"fill_buy", "fill_sell"}]
    upsert_rows(url, api_key, ingest_key, "shadow_events", "event_key", fill_events, opener)
    upsert_rows(url, api_key, ingest_key, "shadow_positions", "account_id,symbol", next_positions, opener)
    if sold:
        delete_rows(
            url,
            api_key,
            ingest_key,
            "shadow_positions",
            {"account_id": f"eq.{SHADOW_ACCOUNT_ID}", "symbol": quoted_in(sold)},
            opener,
        )
    upsert_rows(url, api_key, ingest_key, "shadow_account", "account_id", [next_account], opener)
    upsert_rows(url, api_key, ingest_key, "shadow_nav_daily", "as_of", [nav], opener)
    upsert_rows(url, api_key, ingest_key, "shadow_events", "event_key", other_events, opener)

    fills = sum(1 for item in events if item["event_type"] in {"fill_buy", "fill_sell"})
    blocked = sum(
        1
        for item in events
        if item["event_type"] in {"entry_blocked", "exit_delayed", "skip_insufficient_cash", "skip_t1"}
    )
    snapshot = _snapshot(next_account, next_positions, events, pnl_day)
    return ShadowRefreshStatus("refreshed", fills, blocked, len(events), "shadow cash ledger refreshed", snapshot)
