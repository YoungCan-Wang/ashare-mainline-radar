from __future__ import annotations

from typing import Final

SIGNAL_PROFILES: Final = {
    "loose": {"min_ret_5d": 0.00, "min_amount_ratio": 0.90, "min_high_proximity": -0.08},
    "base": {"min_ret_5d": 0.02, "min_amount_ratio": 1.00, "min_high_proximity": -0.05},
    "strict": {"min_ret_5d": 0.04, "min_amount_ratio": 1.10, "min_high_proximity": -0.03},
}

BASE_ENTRY_PROFILE: Final = SIGNAL_PROFILES["base"]
