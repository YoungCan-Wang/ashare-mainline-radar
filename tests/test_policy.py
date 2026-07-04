from ashare_mainline_radar.models import IntelItem, ThemeSnapshot
from ashare_mainline_radar.policy import build_policy_signal_report, is_policy_item, policy_counts_by_theme


def test_policy_signal_report_groups_official_policy_items() -> None:
    items = [
        IntelItem(
            source="CSRC News",
            title="资本市场支持新质生产力",
            tags=["policy", "regulator"],
            matched_themes=["券商金融", "AI算力"],
        ),
        IntelItem(
            source="Yicai News",
            title="市场关注机器人产业",
            tags=["news"],
            matched_themes=["机器人"],
        ),
    ]
    themes = [
        ThemeSnapshot(
            name="券商金融",
            score=80.0,
            status="主线成立",
            members=3,
            breadth_5d=0.6,
            breadth_20d=0.7,
            avg_ret_5d=0.03,
            avg_ret_20d=0.08,
            amount_heat=1.1,
            catalyst_count=0,
            leaders=[],
        )
    ]

    report = build_policy_signal_report(items, themes)

    assert is_policy_item(items[0])
    assert not is_policy_item(items[1])
    assert policy_counts_by_theme(items)["券商金融"] == 1
    assert report.total_policy_items == 1
    assert report.matched_policy_items == 1
    assert report.signals[0].theme == "券商金融"
    assert report.signals[0].theme_status == "主线成立"


def test_policy_counts_can_use_policy_specific_keywords() -> None:
    items = [
        IntelItem(
            source="NDRC",
            title="人力资源社会保障部介绍就业优先战略",
            tags=["policy", "ministry"],
            matched_themes=["有色金属与铜"],
        )
    ]

    counts = policy_counts_by_theme(items, {"有色金属与铜": ["矿产资源", "战略性矿产"]})

    assert counts == {}
