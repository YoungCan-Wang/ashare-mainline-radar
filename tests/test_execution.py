from __future__ import annotations

import pytest

from ashare_mainline_radar.execution import (
    TradingCostModel,
    apply_execution_costs,
    build_trade_execution_plan,
    daily_limit_price,
    entry_confirmed,
    is_sealed_limit_down,
    is_sealed_limit_up,
    price_limit_rate,
)


def test_stock_costs_include_minimum_commission_and_date_based_taxes() -> None:
    model = TradingCostModel(account_capital=100_000)
    buy = model.fee_breakdown(10_000, "2026-07-17", side="buy")
    sell = model.fee_breakdown(10_000, "2026-07-17", side="sell")
    old_sell = model.fee_breakdown(10_000, "2023-08-25", side="sell")

    assert buy.broker_commission == 5
    assert buy.regulatory_fee == pytest.approx(0.2)
    assert buy.exchange_handling_fee == pytest.approx(0.341)
    assert buy.transfer_fee == pytest.approx(0.1)
    assert buy.stamp_duty == 0
    assert sell.stamp_duty == pytest.approx(5)
    assert old_sell.exchange_handling_fee == pytest.approx(0.487)
    assert old_sell.stamp_duty == pytest.approx(10)


def test_fund_costs_exclude_stock_taxes_and_transfer_fee() -> None:
    fees = TradingCostModel().fee_breakdown(100_000, "2026-07-17", side="sell", is_fund=True)

    assert fees.broker_commission == pytest.approx(20)
    assert fees.exchange_handling_fee == pytest.approx(4)
    assert fees.regulatory_fee == 0
    assert fees.transfer_fee == 0
    assert fees.stamp_duty == 0


def test_execution_costs_apply_slippage_and_all_fees() -> None:
    result = apply_execution_costs(
        10,
        11,
        "2026-07-16",
        "2026-07-17",
        100_000,
        is_fund=False,
        cost_model=TradingCostModel(),
    )

    assert result["entry_price"] == pytest.approx(10.005)
    assert result["exit_price"] == pytest.approx(10.9945)
    assert result["gross_return"] == pytest.approx(0.1)
    assert result["net_return"] < result["gross_return"]


def test_entry_plan_requires_close_confirmation() -> None:
    plan = build_trade_execution_plan(100, "趋势延续")

    assert not entry_confirmed(plan, day_open=98, day_high=99, day_low=96, day_close=97)
    assert entry_confirmed(plan, day_open=97, day_high=100, day_low=96, day_close=99)


def test_price_limits_cover_main_star_chinext_and_beijing() -> None:
    assert price_limit_rate("600000.SH", "浦发银行", "2026-07-17") == 0.10
    assert price_limit_rate("688001.SH", "华兴源创", "2026-07-17") == 0.20
    assert price_limit_rate("300001.SZ", "特锐德", "2020-08-21") == 0.10
    assert price_limit_rate("300001.SZ", "特锐德", "2020-08-24") == 0.20
    assert price_limit_rate("920001.BJ", "北交样本", "2026-07-17") == 0.30
    assert price_limit_rate("920001.BJ", "*ST北交样本", "2026-07-17") == 0.30
    assert price_limit_rate("600001.SH", "*ST样本", "2026-07-03") == 0.05
    assert price_limit_rate("600001.SH", "*ST样本", "2026-07-17") == 0.10
    assert daily_limit_price(9.95, 0.10, direction="up") == 10.95


def test_sealed_price_limits_block_fills() -> None:
    assert is_sealed_limit_up(
        "600000.SH",
        "浦发银行",
        "2026-07-17",
        10,
        day_low=11,
        day_close=11,
        volume=100,
    )
    assert not is_sealed_limit_up(
        "600000.SH",
        "浦发银行",
        "2026-07-17",
        10,
        day_low=10.8,
        day_close=11,
        volume=100,
    )
    assert is_sealed_limit_down(
        "600000.SH",
        "浦发银行",
        "2026-07-17",
        10,
        day_high=9,
        day_close=9,
        volume=100,
    )
