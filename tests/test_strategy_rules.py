from ashare_mainline_radar.strategy_rules import theme_crowding_blocks_entry


def test_theme_crowding_blocks_high_crowding_phases() -> None:
    assert theme_crowding_blocks_entry("山顶高拥挤")
    assert theme_crowding_blocks_entry("山顶高拥挤·兑现不足")
    assert not theme_crowding_blocks_entry("山顶高拥挤·业绩支撑")
    assert not theme_crowding_blocks_entry("半山腰待验证")
    assert not theme_crowding_blocks_entry(None)
