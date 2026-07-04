from ashare_mainline_radar.config import theme_keywords, theme_policy_keywords
from ashare_mainline_radar.intelligence import collect_intelligence_with_status, parse_listing_page, tag_intel_items
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


def test_collect_intelligence_reports_empty_local_status(tmp_path) -> None:
    items, statuses = collect_intelligence_with_status(
        {"local_report_dirs": [str(tmp_path)]},
        {"AI算力": ["算力"]},
    )
    assert items == []
    assert statuses[0].kind == "local_reports"
    assert statuses[0].status == "empty"


def test_parse_listing_page_filters_href_and_extracts_date(monkeypatch) -> None:
    html = """
    <html><body>
      <a href="/nav/index.html">网站首页</a>
      <a href="/policy/2026/item.html">关于推动新质生产力和设备更新的通知</a><span>2026-07-03</span>
      <a href="/policy/2026/report.html">2025年度网站工作年度报表</a><span>2026-07-02</span>
    </body></html>
    """
    monkeypatch.setattr("ashare_mainline_radar.intelligence._fetch_text", lambda _url: html)

    items = parse_listing_page(
        {
            "name": "official",
            "url": "https://example.cn/list/",
            "tags": ["policy"],
            "include_href_keywords": ["/policy/"],
            "exclude_keywords": ["年度报表"],
        }
    )

    assert len(items) == 1
    assert items[0].title == "关于推动新质生产力和设备更新的通知"
    assert items[0].published_at == "2026-07-03"


def test_theme_keywords_include_policy_keywords() -> None:
    config = {
        "themes": [
            {
                "name": "机器人",
                "keywords": ["机器人"],
                "policy_keywords": ["设备更新", "智能制造"],
            }
        ]
    }
    keywords = theme_keywords(config)
    policy_keywords = theme_policy_keywords(config)

    assert keywords["机器人"] == ["机器人", "设备更新", "智能制造"]
    assert policy_keywords["机器人"] == ["设备更新", "智能制造"]
