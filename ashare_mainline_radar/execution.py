from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class TradeExecutionPlan:
    entry_mode: str
    entry_zone_low: float
    entry_zone_high: float
    confirm_price: float
    stop_price: float
    valid_for_days: int
    max_hold_days: int
    max_position_fraction: float
    initial_position_fraction: float

    def to_dict(self) -> dict[str, float | int | str]:
        return asdict(self)


@dataclass(frozen=True)
class FeeBreakdown:
    broker_commission: float
    regulatory_fee: float
    exchange_handling_fee: float
    transfer_fee: float
    stamp_duty: float

    @property
    def total(self) -> float:
        return (
            self.broker_commission
            + self.regulatory_fee
            + self.exchange_handling_fee
            + self.transfer_fee
            + self.stamp_duty
        )

    def to_dict(self) -> dict[str, float]:
        return {**asdict(self), "total": self.total}


@dataclass(frozen=True)
class TradingCostModel:
    account_capital: float = 1_000_000.0
    broker_commission_rate: float = 0.0002
    minimum_commission: float = 5.0
    regulatory_fee_rate: float = 0.00002
    slippage_rate: float = 0.0005

    def exchange_handling_rate(self, trade_date: str, *, is_fund: bool = False) -> float:
        if is_fund:
            return 0.00004
        return 0.0000341 if trade_date >= "2023-08-28" else 0.0000487

    def transfer_fee_rate(self, trade_date: str, *, is_fund: bool = False) -> float:
        if is_fund:
            return 0.0
        return 0.00001 if trade_date >= "2022-04-29" else 0.00002

    def stamp_duty_rate(self, trade_date: str, *, side: str, is_fund: bool = False) -> float:
        if side != "sell" or is_fund:
            return 0.0
        return 0.0005 if trade_date >= "2023-08-28" else 0.001

    def fee_breakdown(
        self,
        notional: float,
        trade_date: str,
        *,
        side: str,
        is_fund: bool = False,
        multiplier: float = 1.0,
    ) -> FeeBreakdown:
        if notional <= 0:
            return FeeBreakdown(0.0, 0.0, 0.0, 0.0, 0.0)
        commission = max(notional * self.broker_commission_rate * multiplier, self.minimum_commission)
        regulatory_rate = 0.0 if is_fund else self.regulatory_fee_rate
        return FeeBreakdown(
            broker_commission=commission,
            regulatory_fee=notional * regulatory_rate * multiplier,
            exchange_handling_fee=notional
            * self.exchange_handling_rate(trade_date, is_fund=is_fund)
            * multiplier,
            transfer_fee=notional * self.transfer_fee_rate(trade_date, is_fund=is_fund) * multiplier,
            stamp_duty=notional
            * self.stamp_duty_rate(trade_date, side=side, is_fund=is_fund)
            * multiplier,
        )

    def assumptions(self) -> dict[str, float | str]:
        return {
            "account_capital": self.account_capital,
            "broker_commission_rate": self.broker_commission_rate,
            "minimum_commission": self.minimum_commission,
            "regulatory_fee_rate": self.regulatory_fee_rate,
            "stock_exchange_handling_rate_since_2023_08_28": 0.0000341,
            "stock_exchange_handling_rate_before_2023_08_28": 0.0000487,
            "stock_transfer_fee_rate_since_2022_04_29": 0.00001,
            "stock_transfer_fee_rate_before_2022_04_29": 0.00002,
            "stock_stamp_duty_sell_rate_since_2023_08_28": 0.0005,
            "stock_stamp_duty_sell_rate_before_2023_08_28": 0.001,
            "slippage_rate_each_side": self.slippage_rate,
            "fund_note": "ETF不收印花税、证管费和过户费，按基金经手费计",
        }


def build_trade_execution_plan(
    last_close: float,
    status: str,
    *,
    hold_days: int = 15,
    max_position_fraction: float = 0.25,
    valid_for_days: int = 5,
    stop_loss: float = 0.08,
) -> TradeExecutionPlan:
    entry_mode = "breakout_close_confirm" if status == "突破观察" else "pullback_close_reclaim"
    return TradeExecutionPlan(
        entry_mode=entry_mode,
        entry_zone_low=round(last_close * 0.955, 2),
        entry_zone_high=round(last_close * 0.985, 2),
        confirm_price=round(last_close * 1.012, 2),
        stop_price=round(last_close * (1 - stop_loss), 2),
        valid_for_days=valid_for_days,
        max_hold_days=hold_days,
        max_position_fraction=max_position_fraction,
        initial_position_fraction=max_position_fraction / 3,
    )


def entry_confirmed(
    plan: TradeExecutionPlan,
    *,
    day_open: float,
    day_high: float,
    day_low: float,
    day_close: float,
) -> bool:
    if min(day_open, day_high, day_low, day_close) <= 0:
        return False
    if plan.entry_mode == "breakout_close_confirm":
        return day_close >= plan.confirm_price and day_close >= day_open
    touched_zone = day_low <= plan.entry_zone_high and day_high >= plan.entry_zone_low
    return touched_zone and day_close >= plan.entry_zone_high and day_close >= day_open and day_close > plan.stop_price


def is_fund_security(name: str) -> bool:
    upper = name.upper()
    return "ETF" in upper or "基金" in name


def price_limit_rate(symbol: str, name: str, trade_date: str) -> float:
    code = symbol.split(".", 1)[0]
    upper_name = name.upper()
    if (upper_name.startswith("ST") or upper_name.startswith("*ST")) and not code.startswith(("300", "688")):
        return 0.05
    if symbol.endswith(".BJ"):
        return 0.30
    if code.startswith("688"):
        return 0.20
    if code.startswith("300"):
        return 0.20 if trade_date >= "2020-08-24" else 0.10
    return 0.10


def daily_limit_price(previous_close: float, rate: float, *, direction: str) -> float:
    multiplier = Decimal("1") + (Decimal(str(rate)) if direction == "up" else -Decimal(str(rate)))
    return float((Decimal(str(previous_close)) * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_sealed_limit_up(
    symbol: str,
    name: str,
    trade_date: str,
    previous_close: float,
    *,
    day_low: float,
    day_close: float,
    volume: float,
) -> bool:
    if volume <= 0:
        return False
    limit_price = daily_limit_price(previous_close, price_limit_rate(symbol, name, trade_date), direction="up")
    return day_low >= limit_price - 0.005 and day_close >= limit_price - 0.005


def is_sealed_limit_down(
    symbol: str,
    name: str,
    trade_date: str,
    previous_close: float,
    *,
    day_high: float,
    day_close: float,
    volume: float,
) -> bool:
    if volume <= 0:
        return False
    limit_price = daily_limit_price(previous_close, price_limit_rate(symbol, name, trade_date), direction="down")
    return day_high <= limit_price + 0.005 and day_close <= limit_price + 0.005


def apply_execution_costs(
    raw_entry_price: float,
    raw_exit_price: float,
    entry_date: str,
    exit_date: str,
    position_notional: float,
    *,
    is_fund: bool,
    cost_model: TradingCostModel,
    multiplier: float = 1.0,
) -> dict[str, float | dict[str, float]]:
    entry_price = raw_entry_price * (1 + cost_model.slippage_rate * multiplier)
    exit_price = raw_exit_price * (1 - cost_model.slippage_rate * multiplier)
    buy_fees = cost_model.fee_breakdown(
        position_notional, entry_date, side="buy", is_fund=is_fund, multiplier=multiplier
    )
    estimated_exit_notional = position_notional * raw_exit_price / raw_entry_price
    sell_fees = cost_model.fee_breakdown(
        estimated_exit_notional, exit_date, side="sell", is_fund=is_fund, multiplier=multiplier
    )
    buy_fee_rate = buy_fees.total / position_notional
    sell_fee_rate = sell_fees.total / estimated_exit_notional
    gross_return = raw_exit_price / raw_entry_price - 1
    net_return = exit_price * (1 - sell_fee_rate) / (entry_price * (1 + buy_fee_rate)) - 1
    return {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "buy_fee_rate": buy_fee_rate,
        "sell_fee_rate": sell_fee_rate,
        "gross_return": gross_return,
        "net_return": net_return,
        "buy_fees": buy_fees.to_dict(),
        "sell_fees": sell_fees.to_dict(),
    }
