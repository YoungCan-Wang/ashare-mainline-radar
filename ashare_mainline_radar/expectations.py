from __future__ import annotations

from datetime import date
from statistics import mean

from .models import (
    ExpectationGapReport,
    ExpectationGapSignal,
    FundamentalReport,
    KlineSeries,
    StrongStockReport,
    SymbolSnapshot,
    cn_market_date_from_ms,
)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _reaction(series: KlineSeries, announce_date: str) -> tuple[float | None, float | None] | None:
    target = _parse_date(announce_date)
    if target is None or len(series.close) < 25:
        return None
    dates = [_parse_date(cn_market_date_from_ms(value)) for value in series.timestamp]
    event_idx = next((idx for idx, item in enumerate(dates) if item is not None and item >= target), None)
    if event_idx is None or event_idx < 20 or event_idx >= len(series.close):
        return None
    before_idx = event_idx - 1
    end_idx = min(event_idx + 2, len(series.close) - 1)
    before = series.close[before_idx]
    reaction = series.close[end_idx] / before - 1 if before else None
    prior_amount = mean(series.amount[event_idx - 20 : event_idx])
    event_amount = mean(series.amount[event_idx : end_idx + 1])
    amount_ratio = event_amount / prior_amount if prior_amount else None
    return reaction, amount_ratio


def _classify(
    fundamental_status: str,
    fundamental_score: float,
    revenue_yoy: float | None,
    net_income_yoy: float | None,
    reaction_3d: float | None,
    amount_ratio: float | None,
) -> tuple[str, float]:
    strong_print = bool(
        fundamental_status == "基本面兑现"
        or fundamental_score >= 72
        or ((revenue_yoy or 0.0) >= 15 and (net_income_yoy or 0.0) >= 30)
    )
    volume_confirmed = amount_ratio is not None and amount_ratio >= 1.08
    if strong_print and reaction_3d is not None and reaction_3d <= -0.03 and volume_confirmed:
        return "利好兑现风险", 90.0
    if strong_print and reaction_3d is not None and reaction_3d >= 0.03 and volume_confirmed:
        return "业绩价格共振", 85.0
    if fundamental_status == "基本面拖累" and reaction_3d is not None and reaction_3d >= 0.03 and volume_confirmed:
        return "利空出尽观察", 72.0
    return "预期差未确认", 50.0


def build_expectation_gap_report(
    fundamentals: FundamentalReport,
    klines: dict[str, KlineSeries],
    snapshots: dict[str, SymbolSnapshot],
) -> ExpectationGapReport:
    signals: list[ExpectationGapSignal] = []
    for item in fundamentals.snapshots:
        if not item.announce_date or (series := klines.get(item.symbol)) is None:
            continue
        reaction = _reaction(series, item.announce_date)
        if reaction is None:
            continue
        reaction_3d, amount_ratio = reaction
        status, score = _classify(
            item.status,
            item.score,
            item.revenue_yoy,
            item.net_income_yoy,
            reaction_3d,
            amount_ratio,
        )
        snapshot = snapshots.get(item.symbol)
        evidence = [f"公告后3日价格反应 {reaction_3d * 100:.2f}%" if reaction_3d is not None else "价格反应缺失"]
        if amount_ratio is not None:
            evidence.append(f"公告窗口成交额/此前20日 {amount_ratio:.2f}x")
        evidence.extend(item.evidence[:2])
        signals.append(
            ExpectationGapSignal(
                symbol=item.symbol,
                name=snapshot.name if snapshot else item.symbol,
                announce_date=item.announce_date,
                status=status,
                score=score,
                reaction_3d=reaction_3d,
                amount_ratio=amount_ratio,
                fundamental_status=item.status,
                evidence=evidence,
            )
        )
    priority = {"利好兑现风险": 3, "业绩价格共振": 2, "利空出尽观察": 1, "预期差未确认": 0}
    signals.sort(key=lambda item: (priority.get(item.status, 0), item.score), reverse=True)
    return ExpectationGapReport(
        signals=signals,
        notes=[
            "业绩好不等于公告后继续上涨；系统同时检查公告窗口的价格和成交反应。",
            "该信号是预期差代理，不等同于卖方一致预期，公告日期或复权数据缺失时不做判断。",
        ],
    )


def apply_expectation_overlay(strong_stocks: StrongStockReport, report: ExpectationGapReport) -> None:
    by_symbol = {item.symbol: item for item in report.signals}
    for candidate in strong_stocks.candidates:
        signal = by_symbol.get(candidate.symbol)
        if signal is None:
            continue
        candidate.expectation_status = signal.status
        if signal.status == "利好兑现风险":
            candidate.score = max(0.0, round(candidate.score - 8.0, 2))
        elif signal.status == "业绩价格共振":
            candidate.score = min(100.0, round(candidate.score + 3.0, 2))
        candidate.reasons.extend(signal.evidence[:2])
    strong_stocks.candidates.sort(key=lambda item: item.score, reverse=True)
