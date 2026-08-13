from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ashare_mainline_radar.execution import TradingCostModel
from ashare_mainline_radar.feishu import build_feishu_card, build_shadow_feishu_card
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
from ashare_mainline_radar.shadow_account import (
    SHADOW_INITIAL_CAPITAL,
    execute_shadow_day,
    lot_size,
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


def test_shadow_feishu_card_is_not_the_radar_gate_card() -> None:
    report = RadarReport(
        generated_at="2026-06-29T00:00:00+00:00",
        data_as_of="2026-07-03",
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
