from ashare_mainline_radar.strategy_rules import (
    EntryChallengerFlags,
    challenger_edge_pass,
    theme_crowding_blocks_entry,
    theme_diffusion_blocks_entry,
    theme_diffusion_stage,
    theme_rel_strength_5d,
)


class _Theme:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_crowding_blocks_except_earnings_support() -> None:
    assert theme_crowding_blocks_entry("山顶高拥挤")
    assert theme_crowding_blocks_entry("山顶高拥挤·兑现不足")
    assert not theme_crowding_blocks_entry("山顶高拥挤·业绩支撑")
    assert not theme_crowding_blocks_entry("半山腰待验证")


def test_diffusion_gate_allows_confirmed_mainline() -> None:
    confirmed = _Theme(
        status="主线成立",
        breadth_5d=0.7,
        breadth_20d=0.65,
        avg_ret_5d=0.03,
        avg_ret_20d=0.08,
        amount_heat=1.1,
    )
    startup = _Theme(
        status="主线候选",
        breadth_5d=0.62,
        breadth_20d=0.4,
        avg_ret_5d=0.02,
        avg_ret_20d=0.01,
        amount_heat=1.05,
    )
    assert theme_diffusion_stage(confirmed) == "主线确认"
    assert not theme_diffusion_blocks_entry(confirmed)
    assert theme_diffusion_stage(startup) == "扩散启动"
    assert theme_diffusion_blocks_entry(startup)


def test_rel_strength_and_challenger_edge_pass() -> None:
    theme = _Theme(avg_ret_5d=0.05)
    assert theme_rel_strength_5d(theme, 0.01) == 0.04
    assert challenger_edge_pass(0.05, -0.01, 0.02, -0.03, 0.03, -0.012, 0.01, -0.04)
    assert not challenger_edge_pass(0.05, -0.01, -0.01, -0.03, 0.03, -0.012, 0.01, -0.04)


def test_entry_flags_default_inactive() -> None:
    flags = EntryChallengerFlags()
    assert not flags.is_active()
    assert EntryChallengerFlags(crowding_veto=True).suffix() == "crowding_veto"
