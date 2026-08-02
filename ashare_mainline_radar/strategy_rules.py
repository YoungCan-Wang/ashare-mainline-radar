from __future__ import annotations

from typing import Final

SIGNAL_PROFILES: Final = {
    "loose": {"min_ret_5d": 0.00, "min_amount_ratio": 0.90, "min_high_proximity": -0.08},
    "base": {"min_ret_5d": 0.02, "min_amount_ratio": 1.00, "min_high_proximity": -0.05},
    "strict": {"min_ret_5d": 0.04, "min_amount_ratio": 1.10, "min_high_proximity": -0.03},
}

BASE_ENTRY_PROFILE: Final = SIGNAL_PROFILES["base"]

# Align with market._price_phase: crowding >= 68 at high range marks 山顶高拥挤.
# Fundamentals may suffix ·兑现不足 / ·业绩支撑; only earnings support may still enter.
CROWDING_ENTRY_BLOCK_PREFIX: Final = "山顶高拥挤"
CROWDING_ENTRY_ALLOW_PHASE: Final = "山顶高拥挤·业绩支撑"


def theme_crowding_blocks_entry(price_phase: str | None) -> bool:
    """Hard veto for new entries when the theme is already high-and-crowded."""
    phase = price_phase or ""
    if not phase.startswith(CROWDING_ENTRY_BLOCK_PREFIX):
        return False
    return phase != CROWDING_ENTRY_ALLOW_PHASE
