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
        table = urlparse(request.full_url).path.rstrip("/").rsplit("/", 1)[-1]
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
                    "payload": {},
                },
                {
                    "event_type": "entry_blocked",
                    "symbol": "000001.SZ",
                    "payload": {"reason": "sealed_limit_up"},
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


def test_sell_persist_rerun_does_not_double_credit() -> None:
    as_of = "2026-07-04"
    symbol = "600001.SH"
    credited_cash = 99500.0
    store = _MemorySupabase(
        {
            "shadow_account": [
                {
                    "account_id": "default",
                    "cash": credited_cash,
                    "equity": credited_cash,
                    "market_value": 8000.0,
                    "initial_capital": SHADOW_INITIAL_CAPITAL,
                    "as_of": as_of,
                }
            ],
            "shadow_positions": [
                {
                    "account_id": "default",
                    "symbol": symbol,
                    "name": "测试股份",
                    "shares": 800,
                    "sellable_shares": 800,
                    "avg_cost": 10.01,
                    "buy_dt": "2026-07-02",
                    "last_mark": 10.0,
                    "opened_at": "2026-07-02T00:00:00+00:00",
                }
            ],
            "shadow_events": [
                {
                    "event_key": f"{as_of}:fill_sell:{symbol}",
                    "account_id": "default",
                    "as_of": as_of,
                    "symbol": symbol,
                    "event_type": "fill_sell",
                    "payload": {"proceeds": 7990.0},
                }
            ],
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
    series = _series(
        symbol,
        ["2026-07-02", "2026-07-03", as_of],
        [10.0, 10.1, 10.0],
        [10.2, 10.3, 10.2],
        [9.9, 9.9, 9.8],
        [10.0, 10.1, 10.0],
    )
    status = refresh_shadow_account(
        as_of=as_of,
        klines={symbol: series},
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="ingest",
        opener=store.opener,
    )
    assert status.status == "refreshed"
    assert store.tables["shadow_account"][0]["cash"] == pytest.approx(credited_cash)
    assert all(row["symbol"] != symbol for row in store.tables["shadow_positions"])
    sells = [row for row in store.tables["shadow_events"] if row["event_type"] == "fill_sell"]
    assert len(sells) == 1
    delete_urls = [request.full_url for request in store.requests if request.get_method() == "DELETE"]
    assert any('in.("600001.SH")' in url for url in delete_urls)


def test_sell_rerun_credits_when_account_row_is_behind() -> None:
    as_of = "2026-07-04"
    previous = "2026-07-03"
    symbol = "600001.SH"
    pre_sell_cash = 92000.0
    proceeds = 7990.0
    store = _MemorySupabase(
        {
            "shadow_account": [
                {
                    "account_id": "default",
                    "cash": pre_sell_cash,
                    "equity": 100000.0,
                    "market_value": 8000.0,
                    "initial_capital": SHADOW_INITIAL_CAPITAL,
                    "as_of": previous,
                }
            ],
            "shadow_positions": [],
            "shadow_events": [
                {
                    "event_key": f"{as_of}:fill_sell:{symbol}",
                    "account_id": "default",
                    "as_of": as_of,
                    "symbol": symbol,
                    "event_type": "fill_sell",
                    "payload": {"proceeds": proceeds},
                }
            ],
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
    status = refresh_shadow_account(
        as_of=as_of,
        klines={
            symbol: _series(
                symbol,
                [previous, as_of],
                [10.0, 10.0],
                [10.2, 10.2],
                [9.9, 9.8],
                [10.0, 10.0],
            )
        },
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="ingest",
        opener=store.opener,
    )
    assert status.status == "refreshed"
    assert store.tables["shadow_account"][0]["cash"] == pytest.approx(pre_sell_cash + proceeds)
    assert store.tables["shadow_account"][0]["as_of"] == as_of
    assert store.tables["shadow_positions"] == []
    assert len([row for row in store.tables["shadow_events"] if row["event_type"] == "fill_sell"]) == 1


def test_buy_rerun_debits_when_account_row_is_behind() -> None:
    as_of = "2026-07-04"
    previous = "2026-07-03"
    symbol = "600001.SH"
    pre_buy_cash = 100000.0
    debit = 8009.51
    store = _MemorySupabase(
        {
            "shadow_account": [
                {
                    "account_id": "default",
                    "cash": pre_buy_cash,
                    "equity": pre_buy_cash,
                    "market_value": 0.0,
                    "initial_capital": SHADOW_INITIAL_CAPITAL,
                    "as_of": previous,
                }
            ],
            "shadow_positions": [
                {
                    "account_id": "default",
                    "symbol": symbol,
                    "name": "测试股份",
                    "shares": 800,
                    "sellable_shares": 0,
                    "avg_cost": 10.01,
                    "buy_dt": as_of,
                    "last_mark": 10.1,
                    "opened_at": "2026-07-04T00:00:00+00:00",
                }
            ],
            "shadow_events": [
                {
                    "event_key": f"{as_of}:fill_buy:{symbol}",
                    "account_id": "default",
                    "as_of": as_of,
                    "symbol": symbol,
                    "event_type": "fill_buy",
                    "qty": 800,
                    "payload": {"debit": debit, "raw_price": 10.0},
                }
            ],
            "radar_trade_events": [
                {
                    "symbol": symbol,
                    "event_type": "opened",
                    "event_date": as_of,
                    "strategy_version": PRODUCTION_PAPER_STRATEGY.version,
                    "payload": {"raw_price": 10.0},
                }
            ],
            "radar_trade_plans": [],
            "shadow_nav_daily": [],
        }
    )
    status = refresh_shadow_account(
        as_of=as_of,
        klines={
            symbol: _series(
                symbol,
                [previous, as_of],
                [10.0, 10.0],
                [10.2, 10.3],
                [9.9, 9.9],
                [10.0, 10.1],
            )
        },
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="ingest",
        opener=store.opener,
    )
    assert status.status == "refreshed"
    assert store.tables["shadow_account"][0]["cash"] == pytest.approx(pre_buy_cash - debit)
    assert store.tables["shadow_account"][0]["as_of"] == as_of
    held = [row for row in store.tables["shadow_positions"] if row["symbol"] == symbol]
    assert len(held) == 1
    assert held[0]["shares"] == 800
    assert len([row for row in store.tables["shadow_events"] if row["event_type"] == "fill_buy"]) == 1


def test_null_as_of_seed_debits_recorded_buy_once() -> None:
    as_of = "2026-07-04"
    symbol = "600001.SH"
    debit = 8009.51
    store = _MemorySupabase(
        {
            "shadow_account": [
                {
                    "account_id": "default",
                    "cash": SHADOW_INITIAL_CAPITAL,
                    "equity": SHADOW_INITIAL_CAPITAL,
                    "market_value": 8080.0,
                    "initial_capital": SHADOW_INITIAL_CAPITAL,
                    "as_of": None,
                }
            ],
            "shadow_positions": [
                {
                    "account_id": "default",
                    "symbol": symbol,
                    "name": "测试股份",
                    "shares": 800,
                    "sellable_shares": 0,
                    "avg_cost": 10.01,
                    "buy_dt": as_of,
                    "last_mark": 10.1,
                }
            ],
            "shadow_events": [
                {
                    "event_key": f"{as_of}:fill_buy:{symbol}",
                    "account_id": "default",
                    "as_of": as_of,
                    "symbol": symbol,
                    "event_type": "fill_buy",
                    "qty": 800,
                    "payload": {"debit": debit, "avg_cost": 10.01, "name": "测试股份"},
                }
            ],
            "radar_trade_events": [
                {
                    "symbol": symbol,
                    "event_type": "opened",
                    "event_date": as_of,
                    "strategy_version": PRODUCTION_PAPER_STRATEGY.version,
                    "payload": {"raw_price": 10.0},
                }
            ],
            "radar_trade_plans": [],
            "shadow_nav_daily": [],
        }
    )
    status = refresh_shadow_account(
        as_of=as_of,
        klines={
            symbol: _series(symbol, ["2026-07-03", as_of], [10.0, 10.0], [10.2, 10.3], [9.9, 9.9], [10.0, 10.1])
        },
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="ingest",
        opener=store.opener,
    )
    assert status.status == "refreshed"
    assert store.tables["shadow_account"][0]["cash"] == pytest.approx(SHADOW_INITIAL_CAPITAL - debit)
    assert store.tables["shadow_account"][0]["as_of"] == as_of
    held = [row for row in store.tables["shadow_positions"] if row["symbol"] == symbol]
    assert len(held) == 1
    assert held[0]["shares"] == 800
    assert len([row for row in store.tables["shadow_events"] if row["event_type"] == "fill_buy"]) == 1


def test_missing_position_is_restored_from_fill_buy() -> None:
    as_of = "2026-07-04"
    previous = "2026-07-03"
    symbol = "600001.SH"
    debit = 8009.51
    store = _MemorySupabase(
        {
            "shadow_account": [
                {
                    "account_id": "default",
                    "cash": SHADOW_INITIAL_CAPITAL,
                    "equity": SHADOW_INITIAL_CAPITAL,
                    "market_value": 0.0,
                    "initial_capital": SHADOW_INITIAL_CAPITAL,
                    "as_of": previous,
                }
            ],
            "shadow_positions": [],
            "shadow_events": [
                {
                    "event_key": f"{as_of}:fill_buy:{symbol}",
                    "account_id": "default",
                    "as_of": as_of,
                    "symbol": symbol,
                    "event_type": "fill_buy",
                    "qty": 800,
                    "price": 10.005,
                    "payload": {"debit": debit, "avg_cost": 10.01, "name": "测试股份", "raw_price": 10.0},
                }
            ],
            "radar_trade_events": [
                {
                    "symbol": symbol,
                    "event_type": "opened",
                    "event_date": as_of,
                    "strategy_version": PRODUCTION_PAPER_STRATEGY.version,
                    "payload": {"raw_price": 10.0},
                }
            ],
            "radar_trade_plans": [],
            "shadow_nav_daily": [],
        }
    )
    status = refresh_shadow_account(
        as_of=as_of,
        klines={
            symbol: _series(symbol, [previous, as_of], [10.0, 10.0], [10.2, 10.3], [9.9, 9.9], [10.0, 10.1])
        },
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="ingest",
        opener=store.opener,
    )
    assert status.status == "refreshed"
    assert store.tables["shadow_account"][0]["cash"] == pytest.approx(SHADOW_INITIAL_CAPITAL - debit)
    held = [row for row in store.tables["shadow_positions"] if row["symbol"] == symbol]
    assert len(held) == 1
    assert held[0]["shares"] == 800
    assert held[0]["sellable_shares"] == 0
    assert len([row for row in store.tables["shadow_events"] if row["event_type"] == "fill_buy"]) == 1


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
    assert any(item["event_type"] == "fill_sell" for item in events)
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
