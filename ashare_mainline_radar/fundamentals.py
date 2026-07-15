from __future__ import annotations

from .models import (
    AccumulationReport,
    FundamentalReport,
    FundamentalSnapshot,
    StrongStockReport,
    ThemeSnapshot,
)


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _same_period_prior(records: list[dict[str, object]], latest: dict[str, object]) -> dict[str, object] | None:
    period = str(latest.get("period_end") or "")
    if len(period) < 10:
        return None
    target = f"{int(period[:4]) - 1}{period[4:]}"
    return next((record for record in records if str(record.get("period_end") or "") == target), None)


def _annualized_roe(roe: float | None, period_end: object) -> float | None:
    if roe is None:
        return None
    period = str(period_end or "")
    try:
        month = int(period[5:7])
    except (TypeError, ValueError):
        return roe
    return roe * (12.0 / month) if month in {3, 6, 9, 12} else roe


def _snapshot(symbol: str, records: list[dict[str, object]], last_close: float | None) -> FundamentalSnapshot | None:
    usable = [record for record in records if record.get("period_end")]
    if not usable:
        return None
    usable.sort(key=lambda record: (str(record.get("period_end")), str(record.get("announce_date") or "")))
    latest = usable[-1]
    prior = _same_period_prior(usable, latest)
    revenue_yoy = _number(latest.get("revenue_yoy"))
    net_income_yoy = _number(latest.get("net_income_yoy"))
    roe = _number(latest.get("roe_diluted")) or _number(latest.get("roe"))
    annualized_roe = _annualized_roe(roe, latest.get("period_end"))
    ocfps = _number(latest.get("ocfps"))
    bps = _number(latest.get("bps"))
    price_to_book = (last_close / bps) if last_close and bps and bps > 0 else None
    prior_revenue = _number(prior.get("revenue_yoy")) if prior else None
    prior_profit = _number(prior.get("net_income_yoy")) if prior else None
    revenue_change = revenue_yoy - prior_revenue if revenue_yoy is not None and prior_revenue is not None else None
    profit_change = net_income_yoy - prior_profit if net_income_yoy is not None and prior_profit is not None else None

    score = 50.0
    if revenue_yoy is not None:
        score += _clip(revenue_yoy / 25.0, -1.0, 1.0) * 12.0
    if net_income_yoy is not None:
        score += _clip(net_income_yoy / 35.0, -1.0, 1.0) * 16.0
    if annualized_roe is not None:
        score += _clip((annualized_roe - 5.0) / 15.0, -0.5, 1.0) * 10.0
    if ocfps is not None:
        score += 5.0 if ocfps > 0 else -7.0
    if revenue_change is not None:
        score += _clip(revenue_change / 15.0, -1.0, 1.0) * 4.0
    if profit_change is not None:
        score += _clip(profit_change / 25.0, -1.0, 1.0) * 6.0
    if roe is not None and roe <= 0:
        score = min(score, 55.0)
    if revenue_yoy is not None and revenue_yoy <= 0:
        score = min(score, 62.0)
    if net_income_yoy is not None and net_income_yoy <= 0:
        score = min(score, 55.0)
    if ocfps is not None and ocfps < 0:
        score = min(score, 72.0)
    score = round(_clip(score, 0.0, 100.0), 2)
    quality_confirmed = all(value is not None and value > 0 for value in (revenue_yoy, net_income_yoy, roe, ocfps))
    if score >= 67 and quality_confirmed:
        status = "基本面兑现"
    elif score >= 62:
        status = "兑现待质量确认"
    elif score >= 52:
        status = "基本面观察"
    else:
        status = "基本面拖累"

    evidence: list[str] = []
    if revenue_yoy is not None:
        evidence.append(f"营收同比 {revenue_yoy:.1f}%")
    if net_income_yoy is not None:
        evidence.append(f"净利润同比 {net_income_yoy:.1f}%")
    if roe is not None:
        roe_text = f"ROE {roe:.1f}%"
        if annualized_roe is not None and annualized_roe != roe:
            roe_text += f"（年化参考 {annualized_roe:.1f}%）"
        evidence.append(roe_text)
    if ocfps is not None:
        evidence.append(f"每股经营现金流 {ocfps:.2f}")
    if price_to_book is not None:
        evidence.append(f"PB参考 {price_to_book:.2f}x")
    if revenue_change is not None or profit_change is not None:
        parts = []
        if revenue_change is not None:
            parts.append(f"营收增速变化 {revenue_change:+.1f}pct")
        if profit_change is not None:
            parts.append(f"利润增速变化 {profit_change:+.1f}pct")
        evidence.append("，".join(parts))

    return FundamentalSnapshot(
        symbol=symbol,
        period_end=str(latest.get("period_end")),
        announce_date=str(latest.get("announce_date")) if latest.get("announce_date") else None,
        revenue_yoy=revenue_yoy,
        net_income_yoy=net_income_yoy,
        roe=roe,
        ocfps=ocfps,
        bps=bps,
        price_to_book=price_to_book,
        revenue_yoy_change=revenue_change,
        net_income_yoy_change=profit_change,
        score=score,
        status=status,
        evidence=evidence,
    )


def build_fundamental_report(
    raw_metrics: dict[str, list[dict[str, object]]],
    prices: dict[str, float],
    requested_symbols: list[str],
) -> FundamentalReport:
    snapshots = [
        item
        for symbol in requested_symbols
        if (item := _snapshot(symbol, raw_metrics.get(symbol, []), prices.get(symbol))) is not None
    ]
    snapshots.sort(key=lambda item: item.score, reverse=True)
    notes = [
        "财务评分使用已公告核心指标，重点检查增长、ROE、经营现金流及同比趋势。",
        "PB仅作横向研究参考；不同行业不可直接用同一阈值比较。",
        "TickFlow核心财务指标不包含卖方一致预期修正，当前不把价格上涨冒充盈利预测上修。",
    ]
    return FundamentalReport(
        snapshots=snapshots,
        covered_symbols=len(snapshots),
        requested_symbols=len(requested_symbols),
        notes=notes,
    )


def apply_fundamental_overlay(
    strong_stocks: StrongStockReport,
    accumulation: AccumulationReport,
    fundamentals: FundamentalReport,
    strong_limit: int,
    accumulation_limit: int,
) -> None:
    by_symbol = {item.symbol: item for item in fundamentals.snapshots}
    for candidate in strong_stocks.candidates:
        item = by_symbol.get(candidate.symbol)
        if item is None:
            continue
        candidate.fundamental_score = item.score
        candidate.fundamental_status = item.status
        candidate.score = round(_clip(candidate.score + (item.score - 55.0) * 0.16, 0.0, 100.0), 2)
        candidate.reasons.extend(item.evidence[:4])
    strong_stocks.candidates.sort(key=lambda item: item.score, reverse=True)
    strong_stocks.candidates[:] = strong_stocks.candidates[:strong_limit]

    for candidate in accumulation.candidates:
        item = by_symbol.get(candidate.symbol)
        if item is None:
            continue
        candidate.fundamental_score = item.score
        candidate.fundamental_status = item.status
        candidate.score = round(_clip(candidate.score + (item.score - 55.0) * 0.20, 0.0, 100.0), 2)
        candidate.reasons.extend(item.evidence[:4])
    accumulation.candidates.sort(key=lambda item: item.score, reverse=True)
    accumulation.candidates[:] = accumulation.candidates[:accumulation_limit]


def apply_theme_fundamental_overlay(
    themes: list[ThemeSnapshot],
    fundamentals: FundamentalReport,
    symbol_to_themes: dict[str, list[str]],
    eligible_symbols: set[str],
) -> None:
    by_theme: dict[str, list[FundamentalSnapshot]] = {}
    configured_count: dict[str, int] = {}
    for symbol, theme_names in symbol_to_themes.items():
        if symbol not in eligible_symbols:
            continue
        for theme_name in theme_names:
            configured_count[theme_name] = configured_count.get(theme_name, 0) + 1
    for item in fundamentals.snapshots:
        for theme_name in symbol_to_themes.get(item.symbol, []):
            by_theme.setdefault(theme_name, []).append(item)

    for theme in themes:
        items = by_theme.get(theme.name, [])
        total = configured_count.get(theme.name, 0)
        if not items or total <= 0:
            if theme.price_phase == "半山腰待验证":
                theme.evidence.append("主题基本面覆盖不足，兑现状态未确认")
            continue
        theme.fundamental_score = round(sum(item.score for item in items) / len(items), 2)
        theme.fundamental_coverage = len(items) / total
        confirmed = [item for item in items if item.status == "基本面兑现"]
        theme.fundamental_confirmed_ratio = len(confirmed) / len(items)
        theme.evidence.append(
            f"主题财务覆盖 {len(items)}/{total}，兑现成员 {len(confirmed)}/{len(items)}，"
            f"平均财务分 {theme.fundamental_score:.1f}"
        )
        if theme.price_phase == "半山腰待验证" and theme.fundamental_score >= 62 and theme.fundamental_confirmed_ratio >= 0.40:
            theme.price_phase = "半山腰兑现"
        elif theme.price_phase == "山顶高拥挤":
            suffix = "业绩支撑" if theme.fundamental_score >= 67 and theme.fundamental_confirmed_ratio >= 0.50 else "兑现不足"
            theme.price_phase = f"山顶高拥挤·{suffix}"
