from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

CN_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def cn_market_date_from_ms(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, timezone.utc).astimezone(CN_MARKET_TIMEZONE).date().isoformat()


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def safe_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current / previous) - 1


@dataclass
class KlineSeries:
    symbol: str
    timestamp: list[int]
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]
    volume: list[float]
    amount: list[float]

    @classmethod
    def from_compact(cls, symbol: str, payload: dict[str, Any]) -> KlineSeries:
        return cls(
            symbol=symbol,
            timestamp=list(payload.get("timestamp") or []),
            open=[float(x) for x in payload.get("open") or []],
            high=[float(x) for x in payload.get("high") or []],
            low=[float(x) for x in payload.get("low") or []],
            close=[float(x) for x in payload.get("close") or []],
            volume=[float(x) for x in payload.get("volume") or []],
            amount=[float(x) for x in payload.get("amount") or []],
        )

    @property
    def usable(self) -> bool:
        return len(self.close) >= 20 and len(self.amount) >= 20

    @property
    def last_timestamp(self) -> int | None:
        return self.timestamp[-1] if self.timestamp else None


@dataclass
class SymbolSnapshot:
    symbol: str
    name: str
    themes: list[str]
    last_close: float
    ret_1d: float | None
    ret_5d: float | None
    ret_20d: float | None
    amount_ma5: float | None
    amount_ma20: float | None
    amount_ratio: float | None
    high_proximity_20d: float | None
    drawdown_20d: float | None
    score: float
    status: str
    ret_60d: float | None = None
    range_position_60d: float | None = None


@dataclass
class IntelItem:
    source: str
    title: str
    url: str | None = None
    published_at: str | None = None
    summary: str | None = None
    tags: list[str] = field(default_factory=list)
    matched_themes: list[str] = field(default_factory=list)


@dataclass
class DataSourceStatus:
    name: str
    kind: str
    status: str
    items: int = 0
    message: str | None = None


@dataclass
class MarketPulse:
    name: str
    status: str
    score: float
    members: int
    avg_ret_5d: float | None
    avg_ret_20d: float | None
    amount_heat: float | None
    positive_20d: float | None
    leaders: list[SymbolSnapshot] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass
class TradingGate:
    level: str
    state: str
    score: float
    max_initial_position_fraction: float
    reasons: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    advance_ratio: float | None = None
    decline_2pct_ratio: float | None = None
    median_stock_return: float | None = None


@dataclass
class MarketStructure:
    status: str
    score: float
    index_count: int
    above_ma5_ratio: float | None
    above_ma20_ratio: float | None
    bullish_alignment_ratio: float | None
    volume_confirmation_ratio: float | None
    higher_high_low_ratio: float | None
    confirmed_breakdown_ratio: float | None
    evidence: list[str] = field(default_factory=list)


@dataclass
class BacktestSummary:
    symbol: str
    name: str
    theme: str
    hold_days: int
    signals: int
    win_rate: float | None
    avg_return: float | None
    median_return: float | None
    best_return: float | None
    worst_return: float | None
    avg_max_drawdown: float | None
    last_signal_date: str | None = None


@dataclass
class StrongStockCandidate:
    symbol: str
    name: str
    theme: str
    last_close: float
    score: float
    status: str
    ret_5d: float | None
    ret_20d: float | None
    amount_ratio: float | None
    high_proximity_20d: float | None
    fundamental_score: float | None = None
    fundamental_status: str = "未覆盖"
    expectation_status: str = "未覆盖"
    reasons: list[str] = field(default_factory=list)
    backtest: BacktestSummary | None = None


@dataclass
class StrongStockReport:
    selected_themes: list[str]
    hold_days: int
    candidates: list[StrongStockCandidate]


@dataclass
class NextBuyPlan:
    symbol: str
    name: str
    theme: str
    decision: str
    priority_score: float
    last_close: float
    entry_plan: str
    invalidation: str
    position_note: str
    evidence: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)


@dataclass
class ThemeBuyGroup:
    theme: str
    theme_status: str
    plans: list[NextBuyPlan]


@dataclass
class NextBuyReport:
    primary: NextBuyPlan | None
    alternatives: list[NextBuyPlan] = field(default_factory=list)
    by_theme: list[ThemeBuyGroup] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class AccumulationCandidate:
    symbol: str
    name: str
    themes: list[str]
    primary_theme: str
    status: str
    score: float
    last_close: float
    range_position_60d: float | None
    drawdown_60d: float | None
    ret_5d: float | None
    ret_20d: float | None
    amount_ratio_5_20: float | None
    amount_ratio_10_30: float | None
    ma20_distance: float | None
    entry_plan: str
    invalidation: str
    fundamental_score: float | None = None
    fundamental_status: str = "未覆盖"
    reasons: list[str] = field(default_factory=list)


@dataclass
class AccumulationReport:
    candidates: list[AccumulationCandidate]
    notes: list[str] = field(default_factory=list)


@dataclass
class GoldenPitCandidate:
    symbol: str
    name: str
    theme: str
    stage: str
    score: float
    last_close: float
    drawdown_from_20d_high: float
    ret_1d: float | None
    ret_5d: float | None
    relative_1d: float | None
    amount_ratio_1_5: float | None
    ma20_distance: float | None
    fundamental_score: float | None
    fundamental_status: str
    bottom_confirmation_score: int
    ma5_flattening: bool
    macd_contracting: bool
    no_new_low: bool
    confirmation: str
    invalidation: str
    action: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class GoldenPitReport:
    candidates: list[GoldenPitCandidate]
    notes: list[str] = field(default_factory=list)


@dataclass
class MonthlyBaseCandidate:
    symbol: str
    name: str
    themes: list[str]
    stage: str
    score: float
    box_months: int
    box_low: float
    box_high: float
    box_width: float
    last_close: float
    box_position: float
    monthly_slope: float
    amount_contraction: float
    prior_peak_multiple: float
    action: str
    confirmation: str
    invalidation: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class MonthlyBaseReport:
    candidates: list[MonthlyBaseCandidate]
    notes: list[str] = field(default_factory=list)


@dataclass
class PolicyThemeSignal:
    theme: str
    theme_status: str
    score: float
    item_count: int
    sources: list[str]
    evidence: list[IntelItem] = field(default_factory=list)


@dataclass
class PolicySignalReport:
    signals: list[PolicyThemeSignal]
    total_policy_items: int
    matched_policy_items: int
    notes: list[str] = field(default_factory=list)


@dataclass
class ResearchTargetReference:
    source: str
    title: str
    target_low: float
    target_high: float
    url: str | None = None
    published_at: str | None = None


@dataclass
class TargetPriceEstimate:
    symbol: str
    name: str
    theme: str
    candidate_type: str
    basis: str
    horizon: str
    last_close: float
    target_low: float
    target_high: float
    upside_low: float
    upside_high: float
    stop_price: float
    downside_to_stop: float
    reward_risk_low: float | None
    reward_risk_high: float | None
    confidence: str
    evidence: list[str] = field(default_factory=list)
    research_targets: list[ResearchTargetReference] = field(default_factory=list)


@dataclass
class TargetPriceReport:
    estimates: list[TargetPriceEstimate]
    notes: list[str] = field(default_factory=list)


@dataclass
class FundamentalSnapshot:
    symbol: str
    period_end: str
    announce_date: str | None
    revenue_yoy: float | None
    net_income_yoy: float | None
    roe: float | None
    ocfps: float | None
    bps: float | None
    price_to_book: float | None
    revenue_yoy_change: float | None
    net_income_yoy_change: float | None
    score: float
    status: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class FundamentalReport:
    snapshots: list[FundamentalSnapshot]
    covered_symbols: int
    requested_symbols: int
    notes: list[str] = field(default_factory=list)


@dataclass
class ExpectationGapSignal:
    symbol: str
    name: str
    announce_date: str
    status: str
    score: float
    reaction_3d: float | None
    amount_ratio: float | None
    fundamental_status: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class ExpectationGapReport:
    signals: list[ExpectationGapSignal]
    notes: list[str] = field(default_factory=list)


@dataclass
class ThemeSnapshot:
    name: str
    score: float
    status: str
    members: int
    breadth_5d: float | None
    breadth_20d: float | None
    avg_ret_5d: float | None
    avg_ret_20d: float | None
    amount_heat: float | None
    catalyst_count: int
    leaders: list[SymbolSnapshot]
    policy_catalyst_count: int = 0
    policy_score: float = 0.0
    vehicles: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    price_phase: str = "阶段未确认"
    crowding_score: float | None = None
    avg_ret_60d: float | None = None
    avg_range_position_60d: float | None = None
    fundamental_score: float | None = None
    fundamental_coverage: float | None = None
    fundamental_confirmed_ratio: float | None = None
    valuation_style: str = "balanced"


@dataclass
class RadarReport:
    generated_at: str
    data_as_of: str | None
    mode: str
    universe: str
    scanned_symbols: int
    data_source: str
    themes: list[ThemeSnapshot]
    market_pulses: list[MarketPulse]
    market_structure: MarketStructure
    trading_gate: TradingGate
    strong_stocks: StrongStockReport
    next_buy: NextBuyReport
    accumulation: AccumulationReport
    golden_pits: GoldenPitReport
    policy_signals: PolicySignalReport
    target_prices: TargetPriceReport
    fundamentals: FundamentalReport
    expectation_gaps: ExpectationGapReport
    leader_tape: list[SymbolSnapshot]
    market_watchlist: list[SymbolSnapshot]
    intel_items: list[IntelItem]
    source_statuses: list[DataSourceStatus]
    warnings: list[str]
    monthly_bases: MonthlyBaseReport = field(default_factory=lambda: MonthlyBaseReport(candidates=[]))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
