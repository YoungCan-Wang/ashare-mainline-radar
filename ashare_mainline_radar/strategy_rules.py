from __future__ import annotations

from dataclasses import dataclass
from typing import Final

SIGNAL_PROFILES: Final = {
    "loose": {"min_ret_5d": 0.00, "min_amount_ratio": 0.90, "min_high_proximity": -0.08},
    "base": {"min_ret_5d": 0.02, "min_amount_ratio": 1.00, "min_high_proximity": -0.05},
    "strict": {"min_ret_5d": 0.04, "min_amount_ratio": 1.10, "min_high_proximity": -0.03},
}

BASE_ENTRY_PROFILE: Final = SIGNAL_PROFILES["base"]

CROWDING_ENTRY_BLOCK_PREFIX: Final = "山顶高拥挤"
CROWDING_ENTRY_ALLOW_PHASE: Final = "山顶高拥挤·业绩支撑"
DIFFUSION_ENTRY_STAGES: Final = frozenset({"主线确认", "主线延续", "主升加速"})
DEFAULT_THEME_CORR_CAP: Final = 0.70


@dataclass(frozen=True)
class EntryChallengerFlags:
    """Optional entry filters for same-run backtest challengers. Production core keeps all off."""

    crowding_veto: bool = False
    diffusion_gate: bool = False
    min_rel_strength_5d: float | None = None
    fundamental_filter: str = "off"  # off | block_drag
    red_unlock_mode: str = "off"  # off | first_non_red
    max_theme_corr: float | None = None

    def is_active(self) -> bool:
        return (
            self.crowding_veto
            or self.diffusion_gate
            or self.min_rel_strength_5d is not None
            or self.fundamental_filter != "off"
            or self.red_unlock_mode != "off"
            or self.max_theme_corr is not None
        )

    def suffix(self) -> str:
        parts: list[str] = []
        if self.crowding_veto:
            parts.append("crowding_veto")
        if self.diffusion_gate:
            parts.append("diffusion_confirm")
        if self.min_rel_strength_5d is not None:
            parts.append("rs_gt_0")
        if self.fundamental_filter == "block_drag":
            parts.append("fund_block_drag")
        if self.red_unlock_mode == "first_non_red":
            parts.append("red_unlock_first_green")
        if self.max_theme_corr is not None:
            parts.append("corr_cap")
        return "_".join(parts)


def theme_crowding_blocks_entry(price_phase: str | None) -> bool:
    phase = price_phase or ""
    if not phase.startswith(CROWDING_ENTRY_BLOCK_PREFIX):
        return False
    return phase != CROWDING_ENTRY_ALLOW_PHASE


def theme_diffusion_stage(theme: object) -> str:
    """Single-bar proxy of lifecycle stage for entry gating (no full history replay)."""
    status = str(getattr(theme, "status", "") or "")
    breadth_5d = float(getattr(theme, "breadth_5d", None) or 0.0)
    breadth_20d = float(getattr(theme, "breadth_20d", None) or 0.0)
    avg_ret_5d = float(getattr(theme, "avg_ret_5d", None) or 0.0)
    avg_ret_20d = float(getattr(theme, "avg_ret_20d", None) or 0.0)
    amount_heat = float(getattr(theme, "amount_heat", None) or 0.0)
    if (
        breadth_5d >= 0.72
        and breadth_20d >= 0.58
        and avg_ret_5d >= 0.05
        and avg_ret_20d >= 0.03
        and amount_heat >= 1.08
    ):
        return "主升加速"
    if status == "主线成立" and (breadth_5d < 0.45 or avg_ret_5d <= 0):
        return "主线回踩"
    if status == "主线成立" and avg_ret_20d > 0:
        return "主线确认"
    if breadth_5d >= 0.60 and avg_ret_5d >= 0.015 and amount_heat >= 1.03:
        return "扩散启动"
    if breadth_5d >= 0.50 and avg_ret_5d > 0 and amount_heat >= 1.0:
        return "资金试探"
    return "弱势等待"


def theme_diffusion_blocks_entry(theme: object) -> bool:
    return theme_diffusion_stage(theme) not in DIFFUSION_ENTRY_STAGES


def theme_rel_strength_5d(theme: object, market_ret_5d: float | None) -> float | None:
    avg_ret_5d = getattr(theme, "avg_ret_5d", None)
    if avg_ret_5d is None or market_ret_5d is None:
        return None
    return float(avg_ret_5d) - float(market_ret_5d)


def challenger_edge_pass(
    challenger_all: float | None,
    challenger_val: float | None,
    challenger_test: float | None,
    challenger_test_dd: float | None,
    core_all: float | None,
    core_val: float | None,
    core_test: float | None,
    core_test_dd: float | None,
) -> bool:
    """Relative to same-run core: all>0 edge, val>=-0.5pp, test>0 edge, test DD not worse by >1pp."""
    all_edge = (challenger_all or 0) - (core_all or 0)
    val_edge = (challenger_val or 0) - (core_val or 0)
    test_edge = (challenger_test or 0) - (core_test or 0)
    dd_ok = (challenger_test_dd or -1) >= (core_test_dd or -1) - 0.01
    return bool(all_edge > 0 and val_edge >= -0.005 and test_edge > 0 and dd_ok)


def challenger_verdict(passed: bool, label: str) -> str:
    if passed:
        return f"{label}相对核心为正，可作为生产默认候选"
    return f"{label}未相对核心形成稳定优势，保持研究开关关闭"
