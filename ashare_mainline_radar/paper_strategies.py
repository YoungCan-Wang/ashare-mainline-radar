from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaperStrategy:
    version: str
    label: str
    theme_exit_days: int
    is_shadow: bool


PRODUCTION_PAPER_STRATEGY = PaperStrategy(
    version="mainline-v1-theme-exit-2d",
    label="生产模拟｜连续2日退出",
    theme_exit_days=2,
    is_shadow=False,
)

FROZEN_EXIT_CHALLENGER = PaperStrategy(
    version="mainline-v2-theme-exit-3d-frozen-20260718",
    label="冻结影子｜连续3日退出",
    theme_exit_days=3,
    is_shadow=True,
)

PAPER_STRATEGIES = (PRODUCTION_PAPER_STRATEGY, FROZEN_EXIT_CHALLENGER)
