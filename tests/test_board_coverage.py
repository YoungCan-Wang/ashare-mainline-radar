from ashare_mainline_radar.board_coverage import (
    BoardThemeMap,
    annotate_hot_boards,
    build_board_coverage_report,
    build_board_theme_map,
    count_persistence_days,
    missing_basket_candidates,
    select_hot_boards,
)
from ashare_mainline_radar.eastmoney_concepts import THEME_PRESETS
from ashare_mainline_radar.feishu import build_feishu_card, build_feishu_text
from ashare_mainline_radar.market import classify_theme
from ashare_mainline_radar.models import (
    AccumulationReport,
    BoardCoverageReport,
    ExpectationGapReport,
    FundamentalReport,
    GoldenPitReport,
    MarketStructure,
    NextBuyReport,
    PolicySignalReport,
    RadarReport,
    StrongStockReport,
    TargetPriceReport,
    TradingGate,
)
from ashare_mainline_radar.report import render_markdown
from ashare_mainline_radar.storage import build_storage_bundle


def _radar(coverage: BoardCoverageReport) -> RadarReport:
    return RadarReport(
        generated_at="2026-09-11T08:00:00+00:00",
        data_as_of="2026-09-11",
        mode="universe",
        universe="CN_Equity_A",
        scanned_symbols=100,
        data_source="test",
        themes=[],
        market_pulses=[],
        market_structure=MarketStructure(
            status="震荡",
            score=50,
            index_count=3,
            above_ma5_ratio=0.5,
            above_ma20_ratio=0.5,
            bullish_alignment_ratio=0.5,
            volume_confirmation_ratio=0.5,
            higher_high_low_ratio=0.5,
            confirmed_breakdown_ratio=0,
            evidence=[],
        ),
        trading_gate=TradingGate("green", "允许寻找买点", 70, 0.25, [], []),
        strong_stocks=StrongStockReport(selected_themes=[], hold_days=15, candidates=[]),
        next_buy=NextBuyReport(primary=None),
        accumulation=AccumulationReport(candidates=[]),
        golden_pits=GoldenPitReport(candidates=[]),
        policy_signals=PolicySignalReport(signals=[], total_policy_items=0, matched_policy_items=0),
        target_prices=TargetPriceReport(estimates=[]),
        fundamentals=FundamentalReport(snapshots=[], covered_symbols=0, requested_symbols=0),
        expectation_gaps=ExpectationGapReport(signals=[]),
        leader_tape=[],
        market_watchlist=[],
        intel_items=[],
        source_statuses=[],
        warnings=[],
        board_coverage=coverage,
    )


def _theme_config() -> dict:
    return {
        "themes": [
            {
                "name": "大消费",
                "keywords": ["大消费", "白酒", "食品饮料"],
                "source": "eastmoney boards: 白酒(BK0896), 食品饮料(BK0438); curated 2026-08-23",
            },
            {
                "name": "农业种植",
                "keywords": ["农业", "种植", "种业", "养殖", "饲料", "粮食", "猪肉"],
                "source": "eastmoney boards: 农业种植(BK0888), 种子(BK1518), 生猪养殖(BK1512); curated 2026-08-23",
            },
            {
                "name": "AI算力",
                "keywords": ["AI", "算力", "CPO"],
            },
        ]
    }


def test_explicit_board_code_maps_to_preset_theme() -> None:
    mapper = build_board_theme_map(_theme_config(), THEME_PRESETS)
    theme, coverage = mapper.map_board("BK0896", "白酒")
    assert theme == "大消费"
    assert coverage == "mapped"
    theme, coverage = mapper.map_board("bk0888", "农业种植")
    assert theme == "农业种植"
    assert coverage == "mapped"


def test_unknown_board_stays_unmapped_not_nearest_theme() -> None:
    mapper = build_board_theme_map(_theme_config(), THEME_PRESETS)
    theme, coverage = mapper.map_board("BK0473", "化肥")
    assert theme is None
    assert coverage == "unmapped"
    theme, coverage = mapper.map_board("BK9999", "农业现代化")
    assert theme is None
    assert coverage == "unmapped"


def test_exact_keyword_fallback_does_not_use_substring() -> None:
    mapper = build_board_theme_map(_theme_config(), THEME_PRESETS)
    theme, coverage = mapper.map_board("BK0001", "CPO概念")
    assert theme == "AI算力"
    assert coverage == "mapped"
    theme, coverage = mapper.map_board("BK0002", "农业")
    assert theme == "农业种植"
    assert coverage == "mapped"


def test_map_is_generated_from_config_not_a_chat_list() -> None:
    mapper = build_board_theme_map(_theme_config(), THEME_PRESETS)
    for name, preset in THEME_PRESETS.items():
        for board in preset["boards"]:
            theme, coverage = mapper.map_board(board["code"], board["name"])
            assert coverage == "mapped"
            assert theme == name


def test_persistence_counts_recent_hot_sessions() -> None:
    history = [
        {"market_date": "2026-09-09", "source": "eastmoney", "board_code": "BK0473"},
        {"market_date": "2026-09-10", "source": "eastmoney", "board_code": "BK0473"},
        {"market_date": "2026-09-10", "source": "eastmoney", "board_code": "BK0896"},
        {"market_date": "2026-09-11", "source": "eastmoney", "board_code": "BK0473"},
    ]
    assert count_persistence_days("eastmoney", "BK0473", "2026-09-11", history) == 3
    assert count_persistence_days("eastmoney", "BK0896", "2026-09-11", history) == 2
    assert count_persistence_days("eastmoney", "BK0000", "2026-09-11", history) == 1


def test_missing_basket_requires_unmapped_and_three_sessions() -> None:
    mapper = build_board_theme_map(_theme_config(), THEME_PRESETS)
    history = [
        {"market_date": "2026-09-09", "source": "eastmoney", "board_code": "BK0473"},
        {"market_date": "2026-09-10", "source": "eastmoney", "board_code": "BK0473"},
        {"market_date": "2026-09-09", "source": "eastmoney", "board_code": "BK0896"},
        {"market_date": "2026-09-10", "source": "eastmoney", "board_code": "BK0896"},
    ]
    snapshots = annotate_hot_boards(
        [
            {
                "source": "eastmoney",
                "board_kind": "industry",
                "board_code": "BK0473",
                "board_name": "化肥",
                "change_pct": 4.2,
                "amount": 9e9,
            },
            {
                "source": "eastmoney",
                "board_kind": "concept",
                "board_code": "BK0896",
                "board_name": "白酒",
                "change_pct": 2.1,
                "amount": 8e9,
            },
            {
                "source": "eastmoney",
                "board_kind": "concept",
                "board_code": "BK7777",
                "board_name": "跨境支付",
                "change_pct": 5.0,
                "amount": 3e9,
            },
        ],
        mapper,
        market_date="2026-09-11",
        history=history,
    )
    missing = missing_basket_candidates(snapshots)
    assert [item.board_name for item in missing] == ["化肥"]
    assert missing[0].coverage == "unmapped"
    assert missing[0].mapped_theme is None
    assert missing[0].persistence_days == 3
    assert all(item.coverage != "主线成立" for item in snapshots)
    assert classify_theme(99, 0.9, 2.0) == "主线成立"
    assert all(item.board_name != "白酒" for item in missing)


def test_hot_set_is_top_n_not_full_catalog() -> None:
    boards = [
        {
            "code": f"BK{idx:04d}",
            "name": f"板块{idx}",
            "kind": "concept",
            "change_pct": float(idx),
            "amount": float(idx * 1e8),
        }
        for idx in range(80)
    ]
    hot = select_hot_boards(boards, amount_limit=10, change_limit=5, cap=12)
    assert len(hot) <= 12
    codes = {item["board_code"] for item in hot}
    assert "BK0079" in codes
    assert "BK0000" not in codes


def test_coverage_report_does_not_classify_mainline() -> None:
    history = [
        {"market_date": "2026-09-09", "source": "eastmoney", "board_code": "BK0473"},
        {"market_date": "2026-09-10", "source": "eastmoney", "board_code": "BK0473"},
    ]
    report = build_board_coverage_report(
        _theme_config(),
        [
            {
                "code": "BK0473",
                "name": "化肥",
                "kind": "industry",
                "change_pct": 3.8,
                "amount": 6e9,
                "source": "eastmoney",
            },
            {
                "code": "BK0896",
                "name": "白酒",
                "kind": "concept",
                "change_pct": 1.2,
                "amount": 7e9,
                "source": "eastmoney",
            },
        ],
        market_date="2026-09-11",
        history=history,
    )
    assert report.missing_basket[0].board_name == "化肥"
    assert report.missing_basket[0].coverage == "unmapped"
    assert report.mapped_footnote[0].board_code == "BK0896"
    assert report.mapped_footnote[0].mapped_theme == "大消费"
    assert "不是主线成立" in report.notes[0]
    assert all("状态为 主线成立" not in note and note != "主线成立" for note in report.notes)


def test_daily_copy_keeps_coverage_observation_separate() -> None:
    history = [
        {"market_date": "2026-09-09", "source": "eastmoney", "board_code": "BK0473"},
        {"market_date": "2026-09-10", "source": "eastmoney", "board_code": "BK0473"},
    ]
    coverage = build_board_coverage_report(
        _theme_config(),
        [
            {
                "code": "BK0473",
                "name": "化肥",
                "kind": "industry",
                "change_pct": 3.8,
                "amount": 6e9,
            }
        ],
        market_date="2026-09-11",
        history=history,
    )
    radar = _radar(coverage)
    markdown = render_markdown(radar)
    text = build_feishu_text(radar)
    card = build_feishu_card(radar)
    contents = "\n".join(
        element.get("content", "") for element in card["body"]["elements"] if element.get("tag") == "markdown"
    )
    assert "## 未入篮热板 / 缺篮候选" in markdown
    assert "覆盖观察，不是主线成立" in markdown
    assert "化肥" in markdown and "`BK0473`" in markdown
    assert "不是买入建议" in markdown
    assert "未入篮热板 / 缺篮候选" in text
    assert "覆盖观察，不是主线成立，不是买入" in text
    assert "未入篮热板 / 缺篮候选" in contents
    assert "主线成立" not in f"{coverage.missing_basket[0].coverage}{coverage.missing_basket[0].mapped_theme}"
    bundle = build_storage_bundle(radar)
    assert bundle["boards"][0]["board_code"] == "BK0473"
    assert bundle["boards"][0]["coverage"] == "unmapped"
    assert bundle["run"]["summary"]["board_coverage"]["missing_basket_count"] == 1
    assert all(theme["theme"] != "化肥" for theme in bundle["themes"])


def test_ambiguous_keyword_stays_unmapped() -> None:
    mapper = BoardThemeMap(
        by_code={},
        by_exact_name={},
        by_keyword={"新能源": {"光伏与储能", "新能源车"}},
    )
    theme, coverage = mapper.map_board("BK1111", "新能源")
    assert theme is None
    assert coverage == "unmapped"
