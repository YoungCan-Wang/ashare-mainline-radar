from ashare_mainline_radar.eastmoney_concepts import (
    THEME_PRESETS,
    build_theme_from_preset,
    code_to_symbol,
    filter_boards,
    offline_theme_from_preset,
    select_scoring_symbols,
    upsert_theme,
)


def test_code_to_symbol_maps_exchanges() -> None:
    assert code_to_symbol("600519") == "600519.SH"
    assert code_to_symbol("000858") == "000858.SZ"
    assert code_to_symbol("159928") == "159928.SZ"
    assert code_to_symbol("600519.SH") == "600519.SH"


def test_select_scoring_symbols_diversifies_boards() -> None:
    constituents = {
        "BK0896": [
            {"symbol": "600519.SH", "code": "600519", "amount": 100},
            {"symbol": "000858.SZ", "code": "000858", "amount": 90},
            {"symbol": "600809.SH", "code": "600809", "amount": 80},
        ],
        "BK0456": [
            {"symbol": "000333.SZ", "code": "000333", "amount": 95},
            {"symbol": "000651.SZ", "code": "000651", "amount": 85},
            {"symbol": "600690.SH", "code": "600690", "amount": 75},
        ],
    }
    symbols = select_scoring_symbols(constituents, per_board_cap=2, max_symbols=4)
    assert symbols == ["600519.SH", "000333.SZ", "000858.SZ", "000651.SZ"]


def test_select_scoring_symbols_keeps_seed_leaders_first() -> None:
    constituents = {
        "BK0896": [{"symbol": "600199.SH", "code": "600199", "amount": 100}],
        "BK0456": [{"symbol": "002050.SZ", "code": "002050", "amount": 99}],
    }
    symbols = select_scoring_symbols(
        constituents,
        per_board_cap=2,
        max_symbols=3,
        seed_symbols=["600519.SH", "000333.SZ"],
    )
    assert symbols[:2] == ["600519.SH", "000333.SZ"]
    assert symbols[2] in {"600199.SH", "002050.SZ"}


def test_one_board_502_does_not_abort_all_presets() -> None:
    """A 502 on BK0509 (传媒游戏 / 网络游戏) must not kill --all-presets."""

    def fake_fetch(board_code: str, pages: int = 2) -> list[dict]:
        if board_code == "BK0509":
            raise RuntimeError(
                "East Money request failed for BK0509: HTTP Error 502: Bad Gateway"
            )
        return [{"symbol": "600000.SH", "code": "600000", "amount": 1}]

    themes = [
        build_theme_from_preset(name, as_of="2026-08-17", fetch_constituents=fake_fetch)
        for name in THEME_PRESETS
    ]
    assert len(themes) == len(THEME_PRESETS)
    media = next(theme for theme in themes if theme["name"] == "传媒游戏")
    assert media["symbols"][0] == THEME_PRESETS["传媒游戏"]["seed_symbols"][0]
    assert "BK0509" in media["source"]


def test_build_theme_from_preset_uses_fetcher() -> None:
    def fake_fetch(board_code: str, pages: int = 2) -> list[dict]:
        data = {
            "BK0896": [{"symbol": "600519.SH", "code": "600519", "amount": 10}],
            "BK0438": [{"symbol": "600887.SH", "code": "600887", "amount": 9}],
            "BK0456": [{"symbol": "000333.SZ", "code": "000333", "amount": 8}],
            "BK0485": [{"symbol": "601888.SH", "code": "601888", "amount": 7}],
            "BK1711": [{"symbol": "605499.SH", "code": "605499", "amount": 6}],
            "BK0482": [{"symbol": "600415.SH", "code": "600415", "amount": 5}],
        }
        return data[board_code]

    theme = build_theme_from_preset("大消费", as_of="2026-07-29", fetch_constituents=fake_fetch)
    assert theme["name"] == "大消费"
    assert theme["valuation_style"] == "balanced"
    assert "600519.SH" in theme["symbols"]
    assert "159928.SZ" in theme["vehicles"]
    assert "eastmoney boards" in theme["source"]
    assert "扩内需" in theme["keywords"]


def test_upsert_theme_replaces_by_name() -> None:
    config = {"themes": [{"name": "AI算力", "symbols": ["1"]}, {"name": "大消费", "symbols": ["old"]}]}
    updated = upsert_theme(config, {"name": "大消费", "symbols": ["new"], "vehicles": []})
    assert updated["themes"][1]["symbols"] == ["new"]
    assert updated["themes"][0]["name"] == "AI算力"


def test_filter_boards_by_keyword() -> None:
    boards = [
        {"name": "白酒", "change_pct": 1.0},
        {"name": "AI算力", "change_pct": 2.0},
        {"name": "食品饮料", "change_pct": 3.0},
    ]
    hits = filter_boards(boards, ["白酒", "食品"])
    assert [item["name"] for item in hits] == ["食品饮料", "白酒"]


def test_offline_presets_cover_common_rotation_themes() -> None:
    required = {
        "大消费",
        "光伏与储能",
        "新能源车",
        "电网设备",
        "电力运营",
        "信创软件",
        "房地产链",
        "航运港口",
        "传媒游戏",
        "农业种植",
        "医疗器械",
        "工程机械",
        "保险",
    }
    assert required.issubset(THEME_PRESETS)
    theme = offline_theme_from_preset("光伏与储能", as_of="2026-07-29")
    assert theme["symbols"][0] == "601012.SH"
    assert "515790.SH" in theme["vehicles"]
