from ashare_mainline_radar.config import DEFAULT_THEME_CONFIG, load_json
from ashare_mainline_radar.cross_market import build_cross_market_report, cross_market_symbols
from ashare_mainline_radar.models import KlineSeries, SymbolSnapshot, ThemeSnapshot


def _series(symbol: str, step: float) -> KlineSeries:
    closes = [100 * (1 + step) ** index for index in range(70)]
    amounts = [100 + index for index in range(70)]
    return KlineSeries(
        symbol=symbol,
        timestamp=list(range(70)),
        open=closes,
        high=[value * 1.01 for value in closes],
        low=[value * 0.99 for value in closes],
        close=closes,
        volume=amounts,
        amount=amounts,
    )


def _a_snapshot(symbol: str, ret_5d: float, ret_20d: float) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        name="A股公司",
        themes=["创新药"],
        last_close=100,
        ret_1d=0.01,
        ret_5d=ret_5d,
        ret_20d=ret_20d,
        amount_ma5=100,
        amount_ma20=100,
        amount_ratio=1,
        high_proximity_20d=-0.01,
        drawdown_20d=-0.01,
        score=80,
        status="趋势延续",
    )


def test_cross_market_confirms_a_h_resonance_without_changing_a_score() -> None:
    config = {
        "cross_market": {
            "themes": [{"name": "创新药", "symbols": ["06160.HK", "09926.HK"]}],
            "ah_pairs": [
                {"company": "百济神州", "a_symbol": "688235.SH", "h_symbol": "06160.HK"}
            ],
        }
    }
    a_theme = ThemeSnapshot("创新药", 90, "主线成立", 10, 0.8, 0.8, 0.08, 0.2, 1.2, 0, [])
    a_snapshot = _a_snapshot("688235.SH", 0.03, 0.10)

    report = build_cross_market_report(
        config,
        {"06160.HK": _series("06160.HK", 0.012), "09926.HK": _series("09926.HK", 0.01)},
        {"06160.HK": {"name": "百济神州"}, "09926.HK": {"name": "康方生物"}},
        [a_theme],
        {a_snapshot.symbol: a_snapshot},
    )

    assert report.themes[0].status == "A港共振"
    assert report.themes[0].a_share_rank == 1
    assert report.ah_pairs[0].leader == "H股领先"
    assert a_theme.score == 90


def test_cross_market_symbols_include_theme_and_pair_only_once() -> None:
    config = {
        "cross_market": {
            "themes": [{"name": "创新药", "symbols": ["06160.HK", "09926.HK"]}],
            "ah_pairs": [{"company": "百济", "a_symbol": "688235.SH", "h_symbol": "06160.HK"}],
        }
    }

    assert cross_market_symbols(config) == ["06160.HK", "09926.HK"]


def test_cross_market_theme_names_align_with_a_share_themes() -> None:
    config = load_json(DEFAULT_THEME_CONFIG)
    a_names = {theme["name"] for theme in config["themes"]}
    cross_themes = (config.get("cross_market") or {}).get("themes") or []
    assert {"大消费", "新能源车", "保险", "高股息红利", "航运港口"}.issubset(
        {basket["name"] for basket in cross_themes}
    )
    for basket in cross_themes:
        assert basket["name"] in a_names
        assert len(basket.get("symbols") or []) >= 4
    pairs = (config.get("cross_market") or {}).get("ah_pairs") or []
    assert len(pairs) >= 15
    assert all(str(pair["h_symbol"]).endswith(".HK") for pair in pairs)
    assert all(str(pair["a_symbol"]).endswith((".SH", ".SZ")) for pair in pairs)
    assert len(cross_market_symbols(config)) >= 60


def test_cross_market_uses_volume_when_hk_amount_is_unavailable() -> None:
    config = {"cross_market": {"themes": [{"name": "创新药", "symbols": ["06160.HK"]}]}}
    series = _series("06160.HK", 0.01)
    series.amount = [0.0] * len(series.amount)

    report = build_cross_market_report(
        config,
        {"06160.HK": series},
        {"06160.HK": {"name": "百济神州"}},
        [],
        {},
    )

    assert report.themes[0].hk_amount_heat is not None
    assert report.themes[0].hk_amount_heat > 1
