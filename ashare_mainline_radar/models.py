from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
    def from_compact(cls, symbol: str, payload: dict[str, Any]) -> "KlineSeries":
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
    vehicles: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


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
    leader_tape: list[SymbolSnapshot]
    market_watchlist: list[SymbolSnapshot]
    intel_items: list[IntelItem]
    source_statuses: list[DataSourceStatus]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
