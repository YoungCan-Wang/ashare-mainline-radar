from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from ashare_mainline_radar.execution import TradingCostModel
from ashare_mainline_radar.feishu import FeishuStatus, build_feishu_card, build_shadow_feishu_card
from ashare_mainline_radar.models import (
    AccumulationReport,
    ExpectationGapReport,
    FundamentalReport,
    GoldenPitReport,
    KlineSeries,
    MarketStructure,
    NextBuyReport,
    PolicySignalReport,
    RadarReport,
    StrongStockReport,
    TargetPriceReport,
    TradingGate,
)
from ashare_mainline_radar.paper_strategies import PRODUCTION_PAPER_STRATEGY
from ashare_mainline_radar.shadow_account import (
    SHADOW_INITIAL_CAPITAL,
    execute_shadow_day,
    lot_size,
    refresh_shadow_account,
    seed_account,
)


def _timestamps(*dates: str) -> list[int]:
    return [int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000) for value in dates]


def _series(symbol: str, dates: list[str], opens: list[float], highs: list[float], lows: list[float], closes: list[float]) -> KlineSeries:
    n = len(dates)
    return KlineSeries(
        symbol=symbol,
        timestamp=_timestamps(*dates),
        open=opens,
        high=highs,
        low=lows,
        close=closes,
        volume=[100.0] * n,
        amount=[1000.0] * n,
    )


def test_seed_account_does_not_stamp_as_of() -> None:
    seeded = seed_account("2026-07-04")
    assert seeded["as_of"] is None
    assert seeded["cash"] == SHADOW_INITIAL_CAPITAL


def test_lot_rounding_and_cash_deducts_fees() -> None:
    assert lot_size("600001.SH") == 100
    assert lot_size("688001.SH") == 200
    as_of = "2026-07-03"
    series = _series(
        "600001.SH",
        ["2026-07-02", as_of],
        [10.0, 10.0],
        [10.2, 10.3],
        [9.9, 9.9],
        [10.0, 10.1],
    )
    model = TradingCostModel(account_capital=SHADOW_INITIAL_CAPITAL)
    account, positions, events = execute_shadow_day(
        seed_account(as_of),
        [],
        as_of=as_of,
        klines={"600001.SH": series},
        buy_intents=[
            {
                "symbol": "600001.SH",
                "name": "测试股份",
                "raw_price": 10.0,
                "initial_position_fraction": 1 / 12,
                "max_position_fraction": 0.25,
                "paper_event_type": "opened",
                "theme": "测试主线",
                "status": "open",
                "entry_mode": "pullback_close_reclaim",
                "confirm_price": 101.2,
                "entry_zone_low": 95.5,
                "entry_zone_high": 98.5,
                "trigger_date": "2026-07-02",
            }
        ],
        sell_intents=[],
        cost_model=model,
    )

    fill = next(item for item in events if item["event_type"] == "fill_buy")
    shares = fill["qty"]
    assert shares == 800
    assert shares % 100 == 0
    fill_price = 10.0 * (1 + model.slippage_rate)
    notional = shares * fill_price
    fees = model.fee_breakdown(notional, as_of, side="buy")
    assert fill["fees"]["total"] == pytest.approx(fees.total)
    assert fill["fees"]["broker_commission"] == 5
    assert account["cash"] == pytest.approx(SHADOW_INITIAL_CAPITAL - notional - fees.total)
    assert positions[0]["sellable_shares"] == 0
    assert positions[0]["avg_cost"] > fill_price
    payload = fill["payload"]
    assert payload["price_basis"] == "next_session_open"
    assert payload["session_open"] == 10.0
    assert payload["raw_price"] == 10.0
    assert payload["slippage_rate"] == model.slippage_rate
    assert payload["fill_price"] == pytest.approx(fill_price)
    assert payload["price_note"] == "隔夜开盘市价挂单，按开盘价成交，再加滑点"
    assert "隔夜开盘市价挂单买入" in payload["reason_note"]
    assert "测试主线" in payload["reason_note"]
    assert "回踩收盘站回" in payload["reason_note"]
    assert payload["theme"] == "测试主线"
    assert payload["entry_mode"] == "pullback_close_reclaim"
    assert "成交理由" in payload["execution_note"]
    assert "价格怎么选的" in payload["execution_note"]
    assert "missing_fields" not in payload


def test_shadow_fill_uses_zone_high_when_paper_opens_on_pullback() -> None:
    as_of = "2026-08-22"
    series = _series(
        "002041.SZ",
        ["2026-08-21", as_of],
        [9.71, 9.80],
        [9.85, 9.85],
        [9.70, 9.60],
        [9.78, 9.70],
    )
    model = TradingCostModel(account_capital=SHADOW_INITIAL_CAPITAL)
    account, positions, events = execute_shadow_day(
        seed_account(as_of),
        [],
        as_of=as_of,
        klines={"002041.SZ": series},
        buy_intents=[
            {
                "symbol": "002041.SZ",
                "name": "登海种业",
                "raw_price": 9.65,
                "initial_position_fraction": 1 / 12,
                "max_position_fraction": 0.25,
                "paper_event_type": "opened",
                "paper_price_basis": "overnight_limit",
                "reason": "overnight_limit",
                "suggested_buy_price": 9.65,
                "working_order_type": "overnight_limit",
                "working_order_note": "次日隔夜限价挂单，建议购买价 9.65",
                "theme": "种业",
                "status": "open",
                "entry_mode": "pullback_close_reclaim",
                "confirm_price": 9.92,
                "entry_zone_low": 9.36,
                "entry_zone_high": 9.65,
                "trigger_date": "2026-08-20",
            }
        ],
        sell_intents=[],
        cost_model=model,
    )

    fill = next(item for item in events if item["event_type"] == "fill_buy")
    payload = fill["payload"]
    assert payload["raw_price"] == 9.65
    assert payload["session_open"] == 9.80
    assert payload["price_basis"] == "overnight_limit"
    assert payload["fill_price"] == pytest.approx(9.65 * (1 + model.slippage_rate))
    assert payload["price_note"] == "隔夜限价挂单，开盘高于建议购买价，按建议购买价限价成交，再加滑点"
    assert "隔夜限价挂单触及建议购买价买入" in payload["reason_note"]
    assert "建议购买价9.65" in payload["reason_note"]
    assert positions[0]["shares"] > 0
    assert account["cash"] < SHADOW_INITIAL_CAPITAL


def test_shadow_does_not_fill_when_paper_expires_without_zone_touch() -> None:
    as_of = "2026-08-25"
    series = _series(
        "002041.SZ",
        ["2026-08-21", as_of],
        [9.71, 9.85],
        [9.85, 9.95],
        [9.70, 9.74],
        [9.78, 9.88],
    )
    account, positions, events = execute_shadow_day(
        seed_account(as_of),
        [],
        as_of=as_of,
        klines={"002041.SZ": series},
        buy_intents=[
            {
                "symbol": "002041.SZ",
                "name": "登海种业",
                "paper_event_type": "expired",
                "paper_price_basis": "overnight_limit_not_tagged",
                "reason": "overnight_limit_not_tagged",
                "suggested_buy_price": 9.65,
                "theme": "种业",
                "status": "expired",
                "entry_mode": "pullback_close_reclaim",
                "confirm_price": 9.92,
                "entry_zone_low": 9.36,
                "entry_zone_high": 9.65,
                "trigger_date": "2026-08-20",
            }
        ],
        sell_intents=[],
        cost_model=TradingCostModel(account_capital=SHADOW_INITIAL_CAPITAL),
    )

    assert positions == []
    assert account["cash"] == SHADOW_INITIAL_CAPITAL
    assert not any(item["event_type"] == "fill_buy" for item in events)
    expired = next(item for item in events if item["event_type"] == "expired")
    assert expired["payload"]["price_basis"] == "overnight_limit_not_tagged"
    assert "未触及建议购买价" in expired["payload"]["price_note"]
    assert "未开仓" in expired["payload"]["reason_note"]


def test_t1_cannot_sell_same_day() -> None:
    as_of = "2026-07-03"
    series = _series(
        "600001.SH",
        ["2026-07-02", as_of],
        [10.0, 10.0],
        [10.2, 10.4],
        [9.9, 9.8],
        [10.0, 10.2],
    )
    model = TradingCostModel(account_capital=SHADOW_INITIAL_CAPITAL)
    account, positions, events = execute_shadow_day(
        seed_account(as_of),
        [],
        as_of=as_of,
        klines={"600001.SH": series},
        buy_intents=[{"symbol": "600001.SH", "name": "测试股份", "raw_price": 10.0}],
        sell_intents=[{"symbol": "600001.SH", "name": "测试股份", "raw_price": 10.2, "reason": "stop"}],
        cost_model=model,
    )

    types = [item["event_type"] for item in events]
    assert "fill_buy" in types
    assert "skip_t1" in types
    assert "fill_sell" not in types
    assert len(positions) == 1
    assert positions[0]["shares"] == 800
    assert positions[0]["sellable_shares"] == 0
    assert account["cash"] < SHADOW_INITIAL_CAPITAL


def test_sealed_limit_up_blocks_buy_and_limit_down_blocks_sell() -> None:
    model = TradingCostModel(account_capital=SHADOW_INITIAL_CAPITAL)
    buy_as_of = "2026-07-03"
    buy_series = _series(
        "600001.SH",
        ["2026-07-02", buy_as_of],
        [97.0, 108.9],
        [100.0, 108.9],
        [96.0, 108.9],
        [99.0, 108.9],
    )
    account, positions, events = execute_shadow_day(
        seed_account(buy_as_of),
        [],
        as_of=buy_as_of,
        klines={"600001.SH": buy_series},
        buy_intents=[{"symbol": "600001.SH", "name": "测试股份", "raw_price": 108.9}],
        sell_intents=[],
        cost_model=model,
    )
    assert positions == []
    assert account["cash"] == SHADOW_INITIAL_CAPITAL
    assert events[0]["event_type"] == "entry_blocked"
    assert events[0]["payload"]["reason"] == "sealed_limit_up"
    assert events[0]["payload"]["price_basis"] == "sealed_limit_up"
    assert "封死涨停" in events[0]["payload"]["price_note"]

    sell_as_of = "2026-07-04"
    sell_series = _series(
        "600001.SH",
        ["2026-07-02", "2026-07-03", sell_as_of],
        [10.0, 9.5, 8.1],
        [10.2, 9.6, 8.1],
        [9.9, 8.9, 8.1],
        [10.0, 9.0, 8.1],
    )
    held = [
        {
            "account_id": "default",
            "symbol": "600001.SH",
            "name": "测试股份",
            "shares": 800,
            "sellable_shares": 800,
            "avg_cost": 10.01,
            "buy_dt": "2026-07-02",
            "last_mark": 9.0,
            "opened_at": "2026-07-02T00:00:00+00:00",
            "exit_pending_reason": "stop",
        }
    ]
    account, positions, events = execute_shadow_day(
        {"account_id": "default", "cash": 92000.0, "equity": 99200.0, "market_value": 7200.0, "initial_capital": SHADOW_INITIAL_CAPITAL},
        held,
        as_of=sell_as_of,
        klines={"600001.SH": sell_series},
        buy_intents=[],
        sell_intents=[{"symbol": "600001.SH", "name": "测试股份", "raw_price": 8.1, "reason": "stop"}],
        cost_model=model,
    )
    assert len(positions) == 1
    assert positions[0]["shares"] == 800
    assert events[0]["event_type"] == "exit_delayed"
    assert events[0]["payload"]["reason"] == "sealed_limit_down"
    assert events[0]["payload"]["price_basis"] == "sealed_limit_down"
    assert "封死跌停" in events[0]["payload"]["price_note"]
    assert account["cash"] == 92000.0


def _radar_report(as_of: str = "2026-07-03") -> RadarReport:
    return RadarReport(
        generated_at="2026-06-29T00:00:00+00:00",
        data_as_of=as_of,
        mode="curated",
        universe="CN_Equity_A",
        scanned_symbols=0,
        data_source="test",
        themes=[],
        market_pulses=[],
        market_structure=MarketStructure(
            status="右侧确认",
            score=80,
            index_count=3,
            above_ma5_ratio=1,
            above_ma20_ratio=1,
            bullish_alignment_ratio=1,
            volume_confirmation_ratio=1,
            higher_high_low_ratio=1,
            confirmed_breakdown_ratio=0,
            evidence=["结构确认"],
        ),
        trading_gate=TradingGate(
            level="green",
            state="允许寻找买点",
            score=70,
            max_initial_position_fraction=1 / 3,
            reasons=["宽基环境正常"],
            allowed_actions=["按触发条件分批"],
        ),
        strong_stocks=StrongStockReport(selected_themes=[], hold_days=5, candidates=[]),
        next_buy=NextBuyReport(primary=None),
        accumulation=AccumulationReport(candidates=[]),
        golden_pits=GoldenPitReport(candidates=[]),
        policy_signals=PolicySignalReport(signals=[], total_policy_items=0, matched_policy_items=0),
        target_prices=TargetPriceReport(estimates=[]),
        fundamentals=FundamentalReport(snapshots=[], covered_symbols=0, requested_symbols=0),
        expectation_gaps=ExpectationGapReport(signals=[]),
        leader_tape=[],
        market_watchlist=[],
        intel_items=[],
        source_statuses=[],
        warnings=[],
    )


class _MemoryResponse:
    status = 204

    def __init__(self, payload: bytes = b"[]"):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.payload


class _MemorySupabase:
    def __init__(self, tables: dict | None = None):
        self.tables = {name: [dict(row) for row in rows] for name, rows in (tables or {}).items()}
        self.requests: list = []

    def opener(self, request, timeout):
        self.requests.append(request)
        path = urlparse(request.full_url).path.rstrip("/")
        if "/rpc/" in path:
            payload = json.loads(request.data.decode("utf-8") if request.data else "{}")
            if path.rsplit("/", 1)[-1] == "apply_shadow_day":
                self._apply_shadow_day(payload)
            return _MemoryResponse()
        table = path.rsplit("/", 1)[-1]
        filters = {key: values[0] for key, values in parse_qs(urlparse(request.full_url).query).items()}
        rows = self.tables.setdefault(table, [])
        method = request.get_method()
        if method == "GET":
            matched = [row for row in rows if self._match(row, filters)]
            return _MemoryResponse(json.dumps(matched).encode("utf-8"))
        if method == "POST":
            payload = json.loads(request.data.decode("utf-8") if request.data else "[]")
            conflict = [part.strip() for part in str(filters.get("on_conflict") or "").split(",") if part.strip()]
            for item in payload:
                idx = next(
                    (
                        i
                        for i, old in enumerate(rows)
                        if conflict and all(str(old.get(key)) == str(item.get(key)) for key in conflict)
                    ),
                    None,
                )
                if idx is None:
                    rows.append(dict(item))
                else:
                    rows[idx] = {**rows[idx], **item}
            return _MemoryResponse()
        if method == "DELETE":
            self.tables[table] = [row for row in rows if not self._match(row, filters)]
            return _MemoryResponse()
        return _MemoryResponse()

    def _apply_shadow_day(self, payload: dict) -> None:
        account = dict(payload["p_account"])
        positions = [dict(item) for item in payload.get("p_positions") or []]
        events = [dict(item) for item in payload.get("p_events") or []]
        nav = dict(payload["p_nav"])
        account_id = str(account["account_id"])
        as_of = str(nav["as_of"])
        accounts = self.tables.setdefault("shadow_account", [])
        idx = next((i for i, row in enumerate(accounts) if str(row.get("account_id")) == account_id), None)
        if idx is None:
            accounts.append(account)
        else:
            accounts[idx] = {**accounts[idx], **account}
        self.tables["shadow_positions"] = [
            row for row in self.tables.get("shadow_positions", []) if str(row.get("account_id")) != account_id
        ] + positions
        self.tables["shadow_events"] = [
            row
            for row in self.tables.get("shadow_events", [])
            if not (str(row.get("account_id")) == account_id and str(row.get("as_of")) == as_of)
        ] + events
        navs = self.tables.setdefault("shadow_nav_daily", [])
        nav_idx = next((i for i, row in enumerate(navs) if str(row.get("as_of")) == as_of), None)
        if nav_idx is None:
            navs.append(nav)
        else:
            navs[nav_idx] = {**navs[nav_idx], **nav}

    @staticmethod
    def _match(row: dict, filters: dict[str, str]) -> bool:
        for key, raw in filters.items():
            if key in {"select", "offset", "limit", "order", "on_conflict"}:
                continue
            value = str(row.get(key) if row.get(key) is not None else "")
            if raw.startswith("eq."):
                if value != raw[3:]:
                    return False
            elif raw.startswith("in.("):
                items = [item.strip().strip('"') for item in raw[4:-1].split(",") if item.strip()]
                if value not in items:
                    return False
        return True


def test_shadow_feishu_card_is_not_the_radar_gate_card() -> None:
    report = _radar_report()
    radar = build_feishu_card(report)
    shadow = build_shadow_feishu_card(
        {
            "as_of": "2026-07-03",
            "account": {
                "cash": 91990.49,
                "equity": 100070.49,
                "market_value": 8080.0,
                "initial_capital": 100000.0,
                "pnl_total": 70.49,
                "pnl_day": 70.49,
            },
            "positions": [
                {
                    "symbol": "600001.SH",
                    "name": "测试股份",
                    "shares": 800,
                    "sellable_shares": 0,
                    "avg_cost": 10.01,
                    "last_mark": 10.10,
                }
            ],
            "today_events": [
                {
                    "event_type": "fill_buy",
                    "symbol": "600001.SH",
                    "qty": 800,
                    "price": 10.005,
                    "fees": {"total": 5.51},
                    "payload": {
                        "reason_note": "主线测试主线；隔夜开盘市价挂单买入",
                        "price_note": "隔夜开盘市价挂单，按开盘价成交，再加滑点",
                        "price_basis": "next_session_open",
                    },
                },
                {
                    "event_type": "entry_blocked",
                    "symbol": "000001.SZ",
                    "payload": {
                        "reason": "sealed_limit_up",
                        "price_basis": "sealed_limit_up",
                        "price_note": "当日封死涨停，未按开盘价成交",
                    },
                },
            ],
        }
    )
    radar_title = radar["header"]["title"]["content"]
    shadow_title = shadow["header"]["title"]["content"]
    radar_text = "\n".join(
        element.get("content", "") for element in radar["body"]["elements"] if element.get("tag") == "markdown"
    )
    shadow_text = "\n".join(
        element.get("content", "") for element in shadow["body"]["elements"] if element.get("tag") == "markdown"
    )
    assert "影子账户" in shadow_title
    assert "现金账本" in shadow_title
    assert "影子账户" not in radar_title
    assert "A股主线作战卡" in radar_title
    assert radar["header"]["template"] == "red"
    assert shadow["header"]["template"] == "blue"
    assert "可尝试建仓" in radar_text
    assert "可尝试建仓" not in shadow_text
    assert "当前主线排名" not in shadow_text
    assert "涨停买不进" in shadow_text
    assert "净值" in shadow_text
    assert "成交理由：主线测试主线；隔夜开盘市价挂单买入" in shadow_text
    assert "价格：隔夜开盘市价挂单，按开盘价成交，再加滑点" in shadow_text
    assert "价格：当日封死涨停，未按开盘价成交" in shadow_text


def _held(symbol: str, *, buy_dt: str = "2026-07-02") -> dict:
    return {
        "account_id": "default",
        "symbol": symbol,
        "name": "测试股份",
        "shares": 800,
        "sellable_shares": 800,
        "avg_cost": 10.01,
        "buy_dt": buy_dt,
        "last_mark": 10.0,
        "opened_at": f"{buy_dt}T00:00:00+00:00",
    }


def test_day_commit_uses_one_rpc_and_same_day_rerun_is_noop() -> None:
    as_of = "2026-07-04"
    previous = "2026-07-03"
    symbol = "600001.SH"
    store = _MemorySupabase(
        {
            "shadow_account": [
                {
                    "account_id": "default",
                    "cash": 92000.0,
                    "equity": 100000.0,
                    "market_value": 8000.0,
                    "initial_capital": SHADOW_INITIAL_CAPITAL,
                    "as_of": previous,
                }
            ],
            "shadow_positions": [_held(symbol)],
            "shadow_events": [],
            "radar_trade_events": [
                {
                    "symbol": symbol,
                    "event_type": "closed",
                    "event_date": as_of,
                    "strategy_version": PRODUCTION_PAPER_STRATEGY.version,
                    "payload": {"raw_price": 10.0, "reason": "收盘跌破失效位", "price_basis": "next_session_open"},
                }
            ],
            "radar_trade_plans": [
                {
                    "symbol": symbol,
                    "name": "测试股份",
                    "theme": "测试主线",
                    "status": "closed",
                    "exit_reason": "收盘跌破失效位",
                    "stop_price": 9.2,
                    "last_evaluated_date": as_of,
                    "strategy_version": PRODUCTION_PAPER_STRATEGY.version,
                }
            ],
            "shadow_nav_daily": [{"as_of": previous, "equity": 100000.0, "cash": 92000.0, "market_value": 8000.0, "pnl_day": 0, "pnl_total": 0}],
        }
    )
    series = _series(
        symbol,
        [previous, as_of],
        [10.0, 10.0],
        [10.2, 10.2],
        [9.9, 9.8],
        [10.0, 10.1],
    )
    kwargs = {
        "as_of": as_of,
        "klines": {symbol: series},
        "supabase_url": "https://example.supabase.co",
        "supabase_publishable_key": "sb_publishable_test",
        "radar_ingest_key": "ingest",
        "opener": store.opener,
    }
    first = refresh_shadow_account(**kwargs)
    assert first.status == "refreshed"
    assert first.message == "shadow cash ledger refreshed"
    rpc_calls = [request for request in store.requests if "/rpc/apply_shadow_day" in request.full_url]
    assert len(rpc_calls) == 1
    cash_after_sell = store.tables["shadow_account"][0]["cash"]
    assert cash_after_sell > 92000.0
    assert store.tables["shadow_account"][0]["as_of"] == as_of
    assert store.tables["shadow_positions"] == []
    assert any(row["event_type"] == "fill_sell" for row in store.tables["shadow_events"])
    assert any(row["event_type"] == "mark" for row in store.tables["shadow_events"])
    sell = next(row for row in store.tables["shadow_events"] if row["event_type"] == "fill_sell")
    assert sell["payload"]["price_basis"] == "next_session_open"
    assert "收盘跌破失效位" in sell["payload"]["reason_note"]
    assert "价格怎么选的" in sell["payload"]["execution_note"]

    second = refresh_shadow_account(**kwargs)
    assert second.status == "refreshed"
    assert "already committed" in second.message
    assert store.tables["shadow_account"][0]["cash"] == pytest.approx(cash_after_sell)
    assert len([request for request in store.requests if "/rpc/apply_shadow_day" in request.full_url]) == 1
    assert len([row for row in store.tables["shadow_events"] if row["event_type"] == "fill_sell"]) == 1


def test_failed_commit_retries_from_last_snapshot() -> None:
    as_of = "2026-07-04"
    previous = "2026-07-03"
    symbol = "600001.SH"
    store = _MemorySupabase(
        {
            "shadow_account": [
                {
                    "account_id": "default",
                    "cash": 92000.0,
                    "equity": 100000.0,
                    "market_value": 8000.0,
                    "initial_capital": SHADOW_INITIAL_CAPITAL,
                    "as_of": previous,
                }
            ],
            "shadow_positions": [_held(symbol)],
            "shadow_events": [],
            "radar_trade_events": [
                {
                    "symbol": symbol,
                    "event_type": "closed",
                    "event_date": as_of,
                    "strategy_version": PRODUCTION_PAPER_STRATEGY.version,
                    "payload": {"raw_price": 10.0},
                }
            ],
            "radar_trade_plans": [],
            "shadow_nav_daily": [],
        }
    )
    failed = {"once": False}

    def opener(request, timeout):
        if "/rpc/apply_shadow_day" in request.full_url and not failed["once"]:
            failed["once"] = True
            raise RuntimeError("commit boom")
        return store.opener(request, timeout)

    series = _series(symbol, [previous, as_of], [10.0, 10.0], [10.2, 10.2], [9.9, 9.8], [10.0, 10.1])
    kwargs = {
        "as_of": as_of,
        "klines": {symbol: series},
        "supabase_url": "https://example.supabase.co",
        "supabase_publishable_key": "sb_publishable_test",
        "radar_ingest_key": "ingest",
        "opener": opener,
    }
    with pytest.raises(RuntimeError, match="commit boom"):
        refresh_shadow_account(**kwargs)
    assert store.tables["shadow_account"][0]["cash"] == pytest.approx(92000.0)
    assert store.tables["shadow_account"][0]["as_of"] == previous
    assert len(store.tables["shadow_positions"]) == 1
    assert store.tables["shadow_events"] == []

    status = refresh_shadow_account(**kwargs)
    assert status.status == "refreshed"
    assert store.tables["shadow_account"][0]["cash"] > 92000.0
    assert store.tables["shadow_account"][0]["as_of"] == as_of
    assert store.tables["shadow_positions"] == []
    assert len([row for row in store.tables["shadow_events"] if row["event_type"] == "fill_sell"]) == 1


def test_first_seed_commits_as_of_only_after_rpc() -> None:
    as_of = "2026-07-04"
    symbol = "600001.SH"
    store = _MemorySupabase(
        {
            "shadow_account": [],
            "shadow_positions": [],
            "shadow_events": [],
            "radar_trade_events": [
                {
                    "symbol": symbol,
                    "event_type": "opened",
                    "event_date": as_of,
                    "strategy_version": PRODUCTION_PAPER_STRATEGY.version,
                    "payload": {"raw_price": 10.0, "name": "测试股份", "price_basis": "next_session_open"},
                }
            ],
            "radar_trade_plans": [
                {
                    "symbol": symbol,
                    "name": "测试股份",
                    "theme": "测试主线",
                    "status": "open",
                    "entry_mode": "pullback_close_reclaim",
                    "confirm_price": 101.2,
                    "entry_zone_low": 95.5,
                    "entry_zone_high": 98.5,
                    "trigger_date": "2026-07-03",
                    "last_evaluated_date": as_of,
                    "strategy_version": PRODUCTION_PAPER_STRATEGY.version,
                    "initial_position_fraction": 1 / 12,
                    "max_position_fraction": 0.25,
                }
            ],
            "shadow_nav_daily": [],
        }
    )
    series = _series(symbol, ["2026-07-03", as_of], [10.0, 10.0], [10.2, 10.3], [9.9, 9.9], [10.0, 10.1])
    status = refresh_shadow_account(
        as_of=as_of,
        klines={symbol: series},
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="ingest",
        opener=store.opener,
    )
    assert status.status == "refreshed"
    assert store.tables["shadow_account"][0]["as_of"] == as_of
    assert store.tables["shadow_account"][0]["cash"] < SHADOW_INITIAL_CAPITAL
    assert len(store.tables["shadow_positions"]) == 1
    assert store.tables["shadow_positions"][0]["shares"] == 800
    assert any("/rpc/apply_shadow_day" in request.full_url for request in store.requests)
    fill = next(row for row in store.tables["shadow_events"] if row["event_type"] == "fill_buy")
    payload = fill["payload"]
    assert payload["price_basis"] == "next_session_open"
    assert payload["reason_note"]
    assert "测试主线" in payload["reason_note"]
    assert "隔夜开盘市价挂单买入" in payload["reason_note"]
    assert payload["price_note"] == "隔夜开盘市价挂单，按开盘价成交，再加滑点"
    assert "成交理由" in payload["execution_note"]
    snapshot_fill = next(item for item in status.snapshot["today_events"] if item["event_type"] == "fill_buy")
    assert snapshot_fill["payload"]["price_basis"] == "next_session_open"
    assert snapshot_fill["payload"]["reason_note"] == payload["reason_note"]


def test_missing_bar_sets_pending_and_retries_next_session() -> None:
    as_of = "2026-07-03"
    next_as_of = "2026-07-04"
    held = [
        {
            "account_id": "default",
            "symbol": "600001.SH",
            "name": "测试股份",
            "shares": 800,
            "sellable_shares": 800,
            "avg_cost": 10.01,
            "buy_dt": "2026-07-01",
            "last_mark": 10.0,
            "opened_at": "2026-07-01T00:00:00+00:00",
        }
    ]
    stale = _series("600001.SH", ["2026-07-01", "2026-07-02"], [10.0, 10.1], [10.2, 10.3], [9.9, 9.9], [10.0, 10.1])
    account, positions, events = execute_shadow_day(
        {"account_id": "default", "cash": 92000.0, "equity": 100000.0, "market_value": 8000.0, "initial_capital": SHADOW_INITIAL_CAPITAL},
        held,
        as_of=as_of,
        klines={"600001.SH": stale},
        buy_intents=[],
        sell_intents=[{"symbol": "600001.SH", "name": "测试股份", "raw_price": 10.0, "reason": "stop"}],
        cost_model=TradingCostModel(account_capital=SHADOW_INITIAL_CAPITAL),
    )
    assert len(positions) == 1
    assert positions[0]["exit_pending_reason"] == "missing_bar"
    assert events[0]["event_type"] == "exit_delayed"
    assert events[0]["payload"]["reason"] == "missing_bar"
    assert account["cash"] == 92000.0

    live = _series(
        "600001.SH",
        ["2026-07-01", "2026-07-02", "2026-07-03", next_as_of],
        [10.0, 10.1, 10.0, 10.2],
        [10.2, 10.3, 10.2, 10.4],
        [9.9, 9.9, 9.8, 10.0],
        [10.0, 10.1, 10.0, 10.3],
    )
    account, positions, events = execute_shadow_day(
        account,
        positions,
        as_of=next_as_of,
        klines={"600001.SH": live},
        buy_intents=[],
        sell_intents=[{"symbol": "600001.SH", "name": "测试股份", "reason": "missing_bar"}],
        cost_model=TradingCostModel(account_capital=SHADOW_INITIAL_CAPITAL),
    )
    assert positions == []
    sell = next(item for item in events if item["event_type"] == "fill_sell")
    assert sell["payload"]["price_basis"] == "session_open"
    assert "改用当日开盘价" in sell["payload"]["price_note"]
    assert "missing_bar" in sell["payload"]["reason_note"]
    assert account["cash"] > 92000.0


def test_past_as_of_does_not_mutate_live_book() -> None:
    live_as_of = "2026-08-12"
    store = _MemorySupabase(
        {
            "shadow_account": [
                {
                    "account_id": "default",
                    "cash": 88000.0,
                    "equity": 96000.0,
                    "market_value": 8000.0,
                    "initial_capital": SHADOW_INITIAL_CAPITAL,
                    "as_of": live_as_of,
                }
            ],
            "shadow_positions": [
                {
                    "account_id": "default",
                    "symbol": "600001.SH",
                    "name": "测试股份",
                    "shares": 800,
                    "sellable_shares": 800,
                    "avg_cost": 10.01,
                    "buy_dt": "2026-08-10",
                    "last_mark": 10.0,
                }
            ],
            "radar_trade_events": [
                {
                    "symbol": "600001.SH",
                    "event_type": "opened",
                    "event_date": "2026-07-01",
                    "strategy_version": PRODUCTION_PAPER_STRATEGY.version,
                    "payload": {"raw_price": 10.0},
                }
            ],
            "radar_trade_plans": [],
            "shadow_events": [],
            "shadow_nav_daily": [],
        }
    )
    status = refresh_shadow_account(
        as_of="2026-07-01",
        klines={},
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="ingest",
        opener=store.opener,
    )
    assert status.status == "skipped"
    assert "historical replay" in status.message
    assert store.tables["shadow_account"][0]["cash"] == 88000.0
    assert store.tables["shadow_account"][0]["as_of"] == live_as_of
    assert len(store.tables["shadow_positions"]) == 1
    assert not any(request.get_method() in {"POST", "DELETE"} and "shadow_" in request.full_url for request in store.requests)


def test_failed_shadow_refresh_does_not_post_empty_card(tmp_path, monkeypatch) -> None:
    from ashare_mainline_radar import cli
    from ashare_mainline_radar.paper_trading import PaperTradeRefreshStatus
    from ashare_mainline_radar.shadow_account import ShadowRefreshStatus, empty_snapshot
    from ashare_mainline_radar.storage import PersistenceStatus

    posted: list[tuple[str, dict]] = []

    monkeypatch.setattr(cli.MainlineRadar, "run", lambda self, **_kwargs: _radar_report())
    monkeypatch.setattr(
        cli,
        "write_report",
        lambda report, output: (
            output.mkdir(parents=True, exist_ok=True),
            (output / "mainline_report.md").write_text("ok", encoding="utf-8"),
            (output / "mainline_report.json").write_text("{}", encoding="utf-8"),
            (output / "mainline_report.md", output / "mainline_report.json"),
        )[-1],
    )
    monkeypatch.setattr(
        cli,
        "persist_report",
        lambda *args, **kwargs: PersistenceStatus("skipped", "none", "run", 0, 0, "off"),
    )
    monkeypatch.setattr(
        cli,
        "refresh_paper_trades",
        lambda *args, **kwargs: PaperTradeRefreshStatus("skipped", 0, 0, 0, "off"),
    )
    monkeypatch.setattr(
        cli,
        "refresh_shadow_account",
        lambda **kwargs: ShadowRefreshStatus("failed", 0, 0, 0, "ledger boom", empty_snapshot("2026-07-03")),
    )

    def fake_post(url, card, timeout=15.0):
        posted.append((url, card["header"]["title"]["content"]))
        return FeishuStatus(status="sent", code=0, message="ok")

    monkeypatch.setattr(cli, "post_feishu_card", fake_post)

    code = cli.main(
        [
            "--output-dir",
            str(tmp_path),
            "--send-feishu",
            "--feishu-webhook-url",
            "https://example.invalid/radar",
            "--shadow-feishu-webhook-url",
            "https://example.invalid/shadow",
            "--storage-backend",
            "none",
        ]
    )
    assert code == 0
    assert posted == [("https://example.invalid/radar", posted[0][1])]
    assert all("影子账户" not in title for _url, title in posted)
    notify = json.loads((tmp_path / "shadow_notification_status.json").read_text(encoding="utf-8"))
    assert notify["status"] == "skipped"
    assert "ledger boom" in notify["message"]
    card = json.loads((tmp_path / "shadow_card.json").read_text(encoding="utf-8"))
    assert "未刷新" in card["header"]["title"]["content"]
    assert "ledger boom" in json.dumps(card, ensure_ascii=False)
