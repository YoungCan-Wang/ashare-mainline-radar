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
    prev_close: list[float] = field(default_factory=list)

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
            prev_close=[float(x) for x in payload.get("prev_close") or []],
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
    relative_percentile: float | None = None


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
    median_stock_return_5d: float | None = None


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
    lifecycle_stage: str = "阶段未确认"
    independence_status: str = "随市主线"
    execution_status: str = "watching"
    entry_mode: str = "pullback_close_reclaim"
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    confirm_price: float | None = None
    stop_price: float | None = None
    valid_for_days: int = 5
    max_hold_days: int = 15
    max_position_fraction: float = 0.25
    initial_position_fraction: float = 1 / 12


@dataclass
class ThemeBuyGroup:
    theme: str
    theme_status: str
    plans: list[NextBuyPlan]
    lifecycle_stage: str = "阶段未确认"
    independence_status: str = "随市主线"
    note: str | None = None


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
    relative_percentile: float | None = None
    leader_concentration: float | None = None


@dataclass
class UnmappedStrengthReport:
    candidates: list[SymbolSnapshot]
    scanned_unmapped: int
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PriceLimitSignal:
    symbol: str
    name: str
    signal_type: str
    action: str
    close: float
    board_rate: float
    prior_streak: int
    themes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PriceLimitWatchReport:
    as_of: str | None
    limit_up_touches: int
    closed_limit_up: int
    first_board_closed: int
    one_price_limit_up: int
    broken_boards: int
    ceiling_to_floor: int
    limit_down_touches: int
    closed_limit_down: int
    one_price_limit_down: int
    broken_floors: int
    floor_to_ceiling: int
    signals: list[PriceLimitSignal] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ThemeLifecycleSignal:
    theme: str
    stage: str
    score: float
    current_status: str
    started_at: str | None
    confirmed_at: str | None
    stage_since: str
    previous_stage: str | None
    transition_age: int
    breadth_5d: float | None
    breadth_20d: float | None
    avg_ret_5d: float | None
    avg_ret_20d: float | None
    amount_heat: float | None
    action: str
    evidence: list[str] = field(default_factory=list)
    relative_strength_5d: float | None = None
    independent_score: float = 0.0
    independence_status: str = "随市主线"
    independence_evidence: list[str] = field(default_factory=list)

    @property
    def is_new_transition(self) -> bool:
        return self.transition_age <= 2


@dataclass
class ThemeLifecycleReport:
    signals: list[ThemeLifecycleSignal]
    history_days: int
    notes: list[str] = field(default_factory=list)


@dataclass
class CrossMarketThemeSignal:
    theme: str
    status: str
    score: float
    hk_members: int
    hk_breadth_5d: float | None
    hk_breadth_20d: float | None
    hk_avg_ret_5d: float | None
    hk_avg_ret_20d: float | None
    hk_amount_heat: float | None
    a_share_rank: int | None
    a_share_status: str | None
    action: str
    leaders: list[SymbolSnapshot] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass
class AHMomentumPair:
    company: str
    a_symbol: str
    h_symbol: str
    a_ret_5d: float | None
    h_ret_5d: float | None
    a_ret_20d: float | None
    h_ret_20d: float | None
    leader: str
    spread_5d: float | None


@dataclass
class CrossMarketReport:
    themes: list[CrossMarketThemeSignal]
    ah_pairs: list[AHMomentumPair]
    notes: list[str] = field(default_factory=list)


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
    theme_lifecycle: ThemeLifecycleReport = field(
        default_factory=lambda: ThemeLifecycleReport(signals=[], history_days=0)
    )
    cross_market: CrossMarketReport = field(default_factory=lambda: CrossMarketReport(themes=[], ah_pairs=[]))
    unmapped_strength: UnmappedStrengthReport = field(
        default_factory=lambda: UnmappedStrengthReport(candidates=[], scanned_unmapped=0)
    )
    price_limit_watch: PriceLimitWatchReport = field(
        default_factory=lambda: PriceLimitWatchReport(
            as_of=None,
            limit_up_touches=0,
            closed_limit_up=0,
            first_board_closed=0,
            one_price_limit_up=0,
            broken_boards=0,
            ceiling_to_floor=0,
            limit_down_touches=0,
            closed_limit_down=0,
            one_price_limit_down=0,
            broken_floors=0,
            floor_to_ceiling=0,
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
