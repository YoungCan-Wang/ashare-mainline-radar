from ashare_mainline_radar.intelligence import tag_intel_items
from ashare_mainline_radar.models import IntelItem


def test_tag_intel_items_matches_theme_keywords() -> None:
    items = [
        IntelItem(source="local", title="AI 算力服务器需求继续提升", summary="液冷和光模块景气度较高"),
        IntelItem(source="local", title="银行股分红稳定", summary="高股息策略受到关注"),
    ]
    tagged = tag_intel_items(
        items,
        {
            "AI算力": ["算力", "光模块"],
            "高股息红利": ["高股息", "分红"],
        },
    )
    assert tagged[0].matched_themes == ["AI算力"]
    assert tagged[1].matched_themes == ["高股息红利"]
