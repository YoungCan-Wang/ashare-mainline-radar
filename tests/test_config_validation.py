from ashare_mainline_radar.config import sanitize_theme_config_instruments


def test_vehicle_name_validation_removes_definite_mismatch_without_mutating_source() -> None:
    config = {
        "themes": [
            {
                "name": "医疗器械",
                "symbols": ["000001.SZ"],
                "vehicles": ["159883.SZ", "562800.SH"],
                "vehicle_name_keywords": ["医疗器械"],
            }
        ]
    }
    instruments = {
        "159883.SZ": {"name": "医疗器械ETF"},
        "562800.SH": {"name": "稀有金属ETF"},
    }

    sanitized, warnings = sanitize_theme_config_instruments(config, instruments)

    assert sanitized["themes"][0]["vehicles"] == ["159883.SZ"]
    assert config["themes"][0]["vehicles"] == ["159883.SZ", "562800.SH"]
    assert any("562800.SH" in warning for warning in warnings)
