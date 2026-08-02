from ashare_mainline_radar.models import SymbolSnapshot, ThemeSnapshot
from ashare_mainline_radar.theme_attribution import suggest_theme_attribution, suggest_unmapped_attributions


def test_keyword_attribution_for_unmapped_name() -> None:
    snapshot = SymbolSnapshot(
        symbol="600000.SH",
        name="某某机器人设备",
        themes=[],
        last_close=10,
        ret_1d=0.02,
        ret_5d=0.06,
        ret_20d=0.12,
        amount_ma5=1,
        amount_ma20=1,
        amount_ratio=1.2,
        high_proximity_20d=-0.02,
        drawdown_20d=-0.03,
        score=88,
        status="主升确认",
    )
    config = {
        "themes": [
            {
                "name": "机器人",
                "keywords": ["机器人"],
                "scoring_symbols": ["600001.SH"],
                "candidate_symbols": ["600001.SH"],
            }
        ]
    }
    suggestions = suggest_theme_attribution(snapshot, config, themes=[])
    assert suggestions
    assert suggestions[0].suggested_theme == "机器人"
    assert suggestions[0].method == "keyword"


def test_mapped_snapshot_skips_suggestion() -> None:
    snapshot = SymbolSnapshot(
        symbol="600000.SH",
        name="某某机器人设备",
        themes=["机器人"],
        last_close=10,
        ret_1d=0.02,
        ret_5d=0.06,
        ret_20d=0.12,
        amount_ma5=1,
        amount_ma20=1,
        amount_ratio=1.2,
        high_proximity_20d=-0.02,
        drawdown_20d=-0.03,
        score=88,
        status="主升确认",
    )
    assert suggest_theme_attribution(snapshot, {"themes": []}, []) == []


def test_unmapped_leader_tape_batch() -> None:
    unmapped = SymbolSnapshot(
        symbol="600000.SH",
        name="固态电池材料",
        themes=[],
        last_close=10,
        ret_1d=0.01,
        ret_5d=0.05,
        ret_20d=0.1,
        amount_ma5=1,
        amount_ma20=1,
        amount_ratio=1.1,
        high_proximity_20d=-0.01,
        drawdown_20d=-0.02,
        score=90,
        status="突破观察",
    )
    mapped = SymbolSnapshot(
        symbol="600001.SH",
        name="已映射",
        themes=["固态电池"],
        last_close=10,
        ret_1d=0.01,
        ret_5d=0.05,
        ret_20d=0.1,
        amount_ma5=1,
        amount_ma20=1,
        amount_ratio=1.1,
        high_proximity_20d=-0.01,
        drawdown_20d=-0.02,
        score=91,
        status="突破观察",
    )
    config = {
        "themes": [
            {
                "name": "固态电池",
                "keywords": ["固态电池"],
                "scoring_symbols": ["600002.SH"],
            }
        ]
    }
    theme = ThemeSnapshot("固态电池", 90, "主线成立", 3, 0.7, 0.6, 0.04, 0.1, 1.1, 0, [])
    result = suggest_unmapped_attributions([mapped, unmapped], config, [theme])
    assert len(result) == 1
    assert result[0].symbol == "600000.SH"
