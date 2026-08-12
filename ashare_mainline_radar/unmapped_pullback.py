from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from .execution import build_trade_execution_plan
from .models import (
    FundamentalReport,
    KlineSeries,
    SymbolSnapshot,
    TradingGate,
    UnmappedPullbackCandidate,
    UnmappedPullbackReport,
    UnmappedStrengthReport,
)

UNMAPPED_THEME = "未映射强势"
MIN_ADVANCE = 0.15
MIN_PULLBACK = 0.06
ROCKET_MAX_PULLBACK = 0.08
LOOKBACK_BARS = 60
BJ_MIN_BARS = 60


@dataclass(frozen=True)
class _Structure:
    style_tag: str
    advance_from_base: float
    max_pullback: float
    pullback_depth: float
    interim_high: float
    base_low: float
    reclaiming: bool
    in_entry_zone: bool
    had_constructive_pullback: bool


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def _is_st(name: str) -> bool:
    upper = name.upper().lstrip()
    return upper.startswith("*ST") or upper.startswith("ST")


def _is_excluded_security(symbol: str, name: str) -> bool:
    upper = name.upper()
    if _is_st(name):
        return True
    return any(token in upper for token in ("ETF", "LOF", "REIT", "指数", "基金", "转债"))


def _fragile_bj_ipo(symbol: str, series: KlineSeries) -> bool:
    return symbol.endswith(".BJ") and len(series.close) < BJ_MIN_BARS


def analyze_pullback_structure(series: KlineSeries, *, lookback: int = LOOKBACK_BARS) -> _Structure | None:
    if len(series.close) < 25:
        return None
    start = max(0, len(series.close) - lookback)
    close = series.close[start:]
    high = series.high[start:]
    low = series.low[start:]
    if len(close) < 25:
        return None

    search_end = max(5, int(len(close) * 0.75))
    base_idx = min(range(search_end), key=lambda idx: low[idx])
    base_low = low[base_idx]
    if base_low <= 0:
        return None

    first_advance_idx: int | None = None
    interim_high = close[base_idx]
    max_pullback = 0.0
    for idx in range(base_idx, len(close)):
        interim_high = max(interim_high, high[idx])
        advance = close[idx] / base_low - 1
        if first_advance_idx is None and advance >= MIN_ADVANCE:
            first_advance_idx = idx
        if first_advance_idx is not None and interim_high > 0:
            dip = low[idx] / interim_high - 1
            max_pullback = min(max_pullback, dip)

    if first_advance_idx is None or interim_high <= 0:
        return None

    last = close[-1]
    advance_from_base = last / base_low - 1
    pullback_depth = last / interim_high - 1
    had_constructive_pullback = max_pullback <= -MIN_PULLBACK
    rocket = abs(max_pullback) < ROCKET_MAX_PULLBACK and pullback_depth > -0.04 and advance_from_base >= MIN_ADVANCE

    ma10 = _avg(close[-10:])
    prior_amount = _avg(series.amount[start + max(0, len(close) - 6) : start + len(close) - 1])
    day_amount = series.amount[-1] if series.amount else None
    volume_ok = bool(day_amount and prior_amount and day_amount >= prior_amount * 0.95)
    reclaiming = bool(
        had_constructive_pullback
        and last > close[-2]
        and (ma10 is None or last >= ma10)
        and pullback_depth >= -0.12
        and (volume_ok or pullback_depth >= -0.03)
    )
    in_entry_zone = bool(had_constructive_pullback and -0.12 <= pullback_depth <= -0.02)

    if rocket and not had_constructive_pullback:
        style_tag = "rocket_watch"
    elif had_constructive_pullback and (reclaiming or in_entry_zone):
        style_tag = "pullback_reclaim"
    else:
        style_tag = "rs_watch"

    return _Structure(
        style_tag=style_tag,
        advance_from_base=advance_from_base,
        max_pullback=max_pullback,
        pullback_depth=pullback_depth,
        interim_high=interim_high,
        base_low=base_low,
        reclaiming=reclaiming,
        in_entry_zone=in_entry_zone,
        had_constructive_pullback=had_constructive_pullback,
    )


def _gate_action(gate: TradingGate | None, buyable: bool) -> str:
    if gate is None:
        return "按触发条件试错" if buyable else "只观察"
    if gate.level == "red":
        return "暂停新仓，只观察"
    if gate.level == "orange":
        return "橙色闸门，仅允许小仓试错" if buyable else "橙色闸门，继续观察"
    return "允许寻找买点" if buyable else "只观察，等待回踩确认"


def _position_fractions(gate: TradingGate | None) -> tuple[float, float]:
    """未映射仓位低于主题 next_buy；橙色闸门再压缩为小试错仓。"""
    if gate and gate.level == "red":
        return 0.0, 0.0
    if gate and gate.level == "orange":
        max_pos = 0.06
    else:
        max_pos = 0.12
    return max_pos, max_pos / 3


def _priority(
    snapshot: SymbolSnapshot,
    structure: _Structure,
    *,
    buyable: bool,
    fundamental_status: str,
    gate: TradingGate | None,
) -> float:
    score = 48.0 + (snapshot.relative_percentile or 0.0) * 0.18
    score += min(12.0, max(-6.0, (snapshot.ret_20d or 0.0) / 0.2 * 12.0))
    score += min(8.0, max(-4.0, ((snapshot.amount_ratio or 1.0) - 1.0) * 16.0))
    if structure.had_constructive_pullback:
        score += 8.0
    if structure.reclaiming:
        score += 7.0
    if structure.in_entry_zone:
        score += 4.0
    if structure.style_tag == "rocket_watch":
        score -= 18.0
    if structure.style_tag == "bj_ipo_speculative":
        score -= 20.0
    if snapshot.ret_5d is not None and snapshot.ret_5d >= 0.15:
        score -= 6.0
    if fundamental_status == "基本面拖累":
        score -= 10.0
    elif fundamental_status == "基本面兑现":
        score += 3.0
    if gate and gate.level == "orange" and structure.style_tag != "pullback_reclaim":
        score -= 8.0
    if buyable:
        score += 4.0
    return round(max(0.0, min(100.0, score)), 2)


def _decision(
    *,
    buyable: bool,
    style_tag: str,
    structure: _Structure,
    gate: TradingGate | None,
    fundamental_status: str,
) -> str:
    if style_tag == "bj_ipo_speculative":
        return "北交所次新脉冲，仅投机观察"
    if style_tag == "rocket_watch":
        return "单边火箭，缺少回踩，禁止追高"
    if fundamental_status == "基本面拖累":
        return "相对强度可见，等待基本面修复"
    if gate and gate.level == "red" and structure.had_constructive_pullback:
        return "回踩结构成立，红色闸门下只观察"
    if buyable and structure.reclaiming:
        return "未映射回踩确认，可小仓试错"
    if buyable and structure.in_entry_zone:
        return "未映射回踩区，等待收盘确认"
    if structure.had_constructive_pullback:
        return "已有回踩，等待重新站稳"
    return "未映射强势观察，等待回踩"


def _build_candidate(
    snapshot: SymbolSnapshot,
    series: KlineSeries,
    structure: _Structure,
    gate: TradingGate | None,
    fundamentals: FundamentalReport | None,
) -> UnmappedPullbackCandidate:
    fundamental = None
    if fundamentals:
        fundamental = next((item for item in fundamentals.snapshots if item.symbol == snapshot.symbol), None)
    fundamental_status = fundamental.status if fundamental else "未覆盖"
    max_pos, initial_pos = _position_fractions(gate)
    execution = build_trade_execution_plan(
        snapshot.last_close,
        "趋势延续",
        hold_days=15,
        max_position_fraction=max(max_pos, 0.01),
        stop_loss=0.08,
    )

    style_tag = structure.style_tag
    if _fragile_bj_ipo(snapshot.symbol, series):
        style_tag = "bj_ipo_speculative"

    structural_buyable = (
        style_tag == "pullback_reclaim"
        and fundamental_status != "基本面拖累"
        and (structure.reclaiming or structure.in_entry_zone)
        and (snapshot.relative_percentile or 0.0) >= 80.0
    )
    buyable = bool(structural_buyable and (gate is None or gate.level != "red") and max_pos > 0)
    if gate and gate.level == "orange" and style_tag != "pullback_reclaim":
        buyable = False

    soft_stop = snapshot.last_close * 0.95
    stop_price = execution.stop_price
    entry_zone_low = execution.entry_zone_low
    entry_zone_high = execution.entry_zone_high
    confirm_price = execution.confirm_price
    if style_tag == "pullback_reclaim" and structure.in_entry_zone:
        entry_zone_low = round(min(entry_zone_low, snapshot.last_close * 0.97), 2)
        entry_zone_high = round(max(entry_zone_high, snapshot.last_close * 0.995), 2)

    reasons = [
        f"横截面相对强度分位 {(snapshot.relative_percentile or 0.0):.1f}%",
        f"自低点推进 {structure.advance_from_base * 100:.1f}%",
        f"过程最大回撤 {structure.max_pullback * 100:.1f}%",
        f"距阶段高点 {structure.pullback_depth * 100:.1f}%",
        f"风格标签 {style_tag}",
    ]
    if snapshot.ret_5d is not None:
        reasons.append(f"5日涨幅 {snapshot.ret_5d * 100:.2f}%")
    if snapshot.ret_20d is not None:
        reasons.append(f"20日涨幅 {snapshot.ret_20d * 100:.2f}%")
    if snapshot.amount_ratio is not None:
        reasons.append(f"成交热度 {snapshot.amount_ratio:.2f}x")
    if structure.reclaiming:
        reasons.append("回踩后出现重新站稳/放量收复迹象")
    if fundamental:
        reasons.append(f"{fundamental.status}，财务分 {fundamental.score:.1f}")

    risk_notes = [
        "未映射强势不等于已确认产业主线；这是研究准备信号，不是自动下单指令。",
        "实盘前需人工确认归因、流动性和公告风险。",
    ]
    if style_tag == "rocket_watch":
        risk_notes.append("单边推进且缺少有效回踩，追高盈亏比差，仅保留观察。")
    if style_tag == "bj_ipo_speculative":
        risk_notes.append("北交所次新/上市脉冲波动大，只作投机观察，不进入可买计划。")
    if gate and gate.level == "orange":
        risk_notes.append("市场闸门为橙色，即使结构合格也只能小仓试错。")
    if gate and gate.level == "red":
        risk_notes.append("市场闸门为红色，禁止新开仓。")

    if buyable:
        entry_plan = (
            f"未来{execution.valid_for_days}个交易日内，最低价触及 "
            f"{entry_zone_low:.2f}-{entry_zone_high:.2f}，收盘重新站上 {entry_zone_high:.2f} 且收阳；"
            "下一交易日开盘未封涨停时执行首笔。"
        )
        position_note = (
            f"未映射试错仓：单仓不超过总资金 {max_pos * 100:.0f}%；"
            f"首笔约占总资金 {initial_pos * 100:.1f}%。"
            "仅在已有浮盈且回踩确认后递减加仓，跌破失效位不补仓。"
        )
    else:
        entry_plan = (
            f"先观察，不主动追价；若重新走出回踩确认，再评估 "
            f"{entry_zone_low:.2f}-{entry_zone_high:.2f} 一带的收盘站稳。"
        )
        position_note = "当前不分配新仓；红色/结构未确认/火箭推进时一律保持观望。"

    invalidation = (
        f"跌破 {soft_stop:.2f} 先降级观察；收盘跌破 {stop_price:.2f} 或相对强度分位跌出前30%，"
        "下一可成交交易日退出假设；封死跌停时顺延。"
    )

    return UnmappedPullbackCandidate(
        symbol=snapshot.symbol,
        name=snapshot.name,
        theme=UNMAPPED_THEME,
        style_tag=style_tag,
        buyable_now=buyable,
        decision=_decision(
            buyable=buyable,
            style_tag=style_tag,
            structure=structure,
            gate=gate,
            fundamental_status=fundamental_status,
        ),
        priority_score=_priority(
            snapshot,
            structure,
            buyable=buyable,
            fundamental_status=fundamental_status,
            gate=gate,
        ),
        last_close=snapshot.last_close,
        entry_plan=entry_plan,
        invalidation=invalidation,
        position_note=position_note,
        gate_action=_gate_action(gate, buyable),
        ret_5d=snapshot.ret_5d,
        ret_20d=snapshot.ret_20d,
        amount_ratio=snapshot.amount_ratio,
        high_proximity_20d=snapshot.high_proximity_20d,
        relative_percentile=snapshot.relative_percentile,
        advance_from_base=round(structure.advance_from_base, 4),
        max_pullback=round(structure.max_pullback, 4),
        pullback_depth=round(structure.pullback_depth, 4),
        fundamental_status=fundamental_status,
        fundamental_score=fundamental.score if fundamental else None,
        reasons=reasons,
        risk_notes=risk_notes,
        execution_status="watching",
        entry_mode="pullback_close_reclaim",
        entry_zone_low=entry_zone_low,
        entry_zone_high=entry_zone_high,
        confirm_price=confirm_price,
        stop_price=stop_price,
        valid_for_days=execution.valid_for_days,
        max_hold_days=execution.max_hold_days,
        max_position_fraction=max_pos,
        initial_position_fraction=initial_pos,
    )


def _seed_snapshots(
    unmapped_strength: UnmappedStrengthReport | None,
    snapshots: dict[str, SymbolSnapshot],
    instruments: dict[str, dict[str, Any]],
) -> list[SymbolSnapshot]:
    seeded: dict[str, SymbolSnapshot] = {}
    if unmapped_strength:
        for item in unmapped_strength.candidates:
            seeded[item.symbol] = item
    for item in snapshots.values():
        if item.themes or item.symbol in seeded:
            continue
        if _is_excluded_security(item.symbol, item.name):
            continue
        if not item.symbol.endswith((".SH", ".SZ", ".BJ")):
            continue
        name = str((instruments.get(item.symbol) or {}).get("name") or item.name)
        if _is_excluded_security(item.symbol, name):
            continue
        if (
            (item.relative_percentile or 0.0) >= 80.0
            and item.ret_5d is not None
            and item.ret_5d > 0.02
            and item.ret_20d is not None
            and item.ret_20d > 0.05
            and item.amount_ratio is not None
            and item.amount_ratio >= 1.0
            and item.high_proximity_20d is not None
            and item.high_proximity_20d > -0.08
        ):
            seeded[item.symbol] = item
    return list(seeded.values())


def build_unmapped_pullback_report(
    *,
    snapshots: dict[str, SymbolSnapshot],
    klines: dict[str, KlineSeries],
    instruments: dict[str, dict[str, Any]],
    trading_gate: TradingGate | None,
    unmapped_strength: UnmappedStrengthReport | None = None,
    fundamentals: FundamentalReport | None = None,
    limit: int = 20,
    buyable_limit: int = 5,
) -> UnmappedPullbackReport:
    seeds = _seed_snapshots(unmapped_strength, snapshots, instruments)
    candidates: list[UnmappedPullbackCandidate] = []
    for snapshot in seeds:
        if _is_st(snapshot.name) or _is_excluded_security(snapshot.symbol, snapshot.name):
            continue
        series = klines.get(snapshot.symbol)
        if not series:
            continue
        structure = analyze_pullback_structure(series)
        if structure is None:
            continue
        if _fragile_bj_ipo(snapshot.symbol, series):
            structure = _Structure(
                style_tag="bj_ipo_speculative",
                advance_from_base=structure.advance_from_base,
                max_pullback=structure.max_pullback,
                pullback_depth=structure.pullback_depth,
                interim_high=structure.interim_high,
                base_low=structure.base_low,
                reclaiming=False,
                in_entry_zone=False,
                had_constructive_pullback=structure.had_constructive_pullback,
            )
        candidates.append(_build_candidate(snapshot, series, structure, trading_gate, fundamentals))

    candidates.sort(key=lambda item: (item.buyable_now, item.priority_score), reverse=True)
    ranked = candidates[:limit]
    buyable = [item for item in ranked if item.buyable_now][:buyable_limit]
    notes = [
        "未映射回踩池把“主题篮子漏掉的相对强度”转成条件化交易计划，不自动升级为产业主线。",
        "优先 pullback/reclaim（回踩再站稳），橙色/红色闸门下禁止追火箭式单边行情。",
        "ST/*ST 剔除；北交所上市脉冲仅投机观察；可买计划仓位受交易闸门约束。",
        "输出供研究准备，不是自动券商下单指令。",
    ]
    if trading_gate and trading_gate.level == "red":
        notes.append(f"当前交易闸门为“{trading_gate.state}”，全部未映射计划只观察、不生成可买动作。")
    elif not buyable:
        notes.append("当前没有同时满足回踩结构、相对强度和闸门约束的可买未映射候选。")
    return UnmappedPullbackReport(
        candidates=ranked,
        buyable_now=buyable,
        scanned=len(seeds),
        notes=notes,
    )


def pullback_symbols_for_fundamentals(
    unmapped_strength: UnmappedStrengthReport | None,
    snapshots: dict[str, SymbolSnapshot],
    instruments: dict[str, dict[str, Any]],
) -> list[str]:
    return [item.symbol for item in _seed_snapshots(unmapped_strength, snapshots, instruments)]
