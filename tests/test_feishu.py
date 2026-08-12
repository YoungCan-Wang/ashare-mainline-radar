import json

import pytest

from ashare_mainline_radar.feishu import (
    FeishuStatus,
    _hold_ready,
    _normalize_dashboard_url,
    _target_text,
    _waiting_note,
    build_feishu_card,
    build_feishu_text,
    write_feishu_status,
)
from ashare_mainline_radar.models import (
    AccumulationReport,
    BacktestSummary,
    CrossMarketReport,
    CrossMarketThemeSignal,
    ExpectationGapReport,
    FundamentalReport,
    GoldenPitReport,
    MarketStructure,
    MonthlyBaseCandidate,
    MonthlyBaseReport,
    NextBuyPlan,
    NextBuyReport,
    PolicySignalReport,
    RadarReport,
    PriceLimitSignal,
    PriceLimitWatchReport,
    StrongStockCandidate,
    StrongStockReport,
    TargetPriceEstimate,
    TargetPriceReport,
    ThemeLifecycleReport,
    ThemeLifecycleSignal,
    ThemeSnapshot,
    TradingGate,
    UnmappedPullbackCandidate,
    UnmappedPullbackReport,
)


def _green_gate() -> TradingGate:
    return TradingGate(
        level="green",
        state="允许寻找买点",
        score=70,
        max_initial_position_fraction=1 / 3,
        reasons=["宽基环境正常"],
        allowed_actions=["按触发条件分批"],
    )


def _market_structure() -> MarketStructure:
    return MarketStructure(
        status="右侧确认",
        score=80,
        index_count=3,
        above_ma5_ratio=1,
        above_ma20_ratio=1,
        bullish_alignment_ratio=1,
        volume_confirmation_ratio=1,
        higher_high_low_ratio=1,
        confirmed_breakdown_ratio=0,
        evidence=["结构确认"],
    )


def test_build_feishu_text_minimal_report() -> None:
    report = RadarReport(
        generated_at="2026-06-29T00:00:00+00:00",
        data_as_of="2026-06-26",
        mode="curated",
        universe="CN_Equity_A",
        scanned_symbols=0,
        data_source="test",
        themes=[],
        market_pulses=[],
        market_structure=_market_structure(),
        trading_gate=_green_gate(),
        strong_stocks=StrongStockReport(selected_themes=[], hold_days=5, candidates=[]),
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
    )
    text = build_feishu_text(report)
    assert "A股市场主线雷达" in text
    assert "2026-06-26" in text
    card = build_feishu_card(report)
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "red"
    contents = "\n".join(
        element.get("content", "") for element in card["body"]["elements"] if element.get("tag") == "markdown"
    )
    assert "可尝试建仓" in contents
    assert "已有仓位可继续持有" in contents
    assert "10-20个交易日" in contents

    report.price_limit_watch = PriceLimitWatchReport(
        as_of="2026-06-26",
        limit_up_touches=2,
        closed_limit_up=1,
        first_board_closed=1,
        one_price_limit_up=0,
        broken_boards=1,
        ceiling_to_floor=0,
        limit_down_touches=1,
        closed_limit_down=0,
        one_price_limit_down=0,
        broken_floors=1,
        floor_to_ceiling=0,
        signals=[
            PriceLimitSignal(
                symbol="000001.SZ",
                name="测试股份",
                signal_type="首板封住",
                action="后验观察",
                close=11,
                board_rate=0.1,
                prior_streak=0,
                themes=["测试主题"],
            )
        ],
    )
    card = build_feishu_card(report)
    contents = "\n".join(
        element.get("content", "") for element in card["body"]["elements"] if element.get("tag") == "markdown"
    )
    assert "涨跌停行为观察" in contents
    assert "首板封住" in contents

    report.unmapped_pullback = UnmappedPullbackReport(
        candidates=[
            UnmappedPullbackCandidate(
                symbol="600000.SH",
                name="未映射样例",
                theme="未映射强势",
                style_tag="pullback_reclaim",
                buyable_now=True,
                decision="未映射回踩确认，可小仓试错",
                priority_score=81.0,
                last_close=12.0,
                entry_plan="回踩确认",
                invalidation="跌破止损",
                position_note="试错仓",
                gate_action="允许寻找买点",
                entry_zone_low=11.4,
                entry_zone_high=11.8,
                confirm_price=12.1,
                stop_price=11.0,
            )
        ],
        buyable_now=[
            UnmappedPullbackCandidate(
                symbol="600000.SH",
                name="未映射样例",
                theme="未映射强势",
                style_tag="pullback_reclaim",
                buyable_now=True,
                decision="未映射回踩确认，可小仓试错",
                priority_score=81.0,
                last_close=12.0,
                entry_plan="回踩确认",
                invalidation="跌破止损",
                position_note="试错仓",
                gate_action="允许寻找买点",
                entry_zone_low=11.4,
                entry_zone_high=11.8,
                confirm_price=12.1,
                stop_price=11.0,
            )
        ],
        scanned=1,
    )
    card = build_feishu_card(report)
    contents = "\n".join(
        element.get("content", "") for element in card["body"]["elements"] if element.get("tag") == "markdown"
    )
    assert "未映射相对强度回踩" in contents
    assert "600000.SH" in contents
    text = build_feishu_text(report)
    assert "未映射相对强度回踩" in text

    report.monthly_bases = MonthlyBaseReport(
        candidates=[
            MonthlyBaseCandidate(
                symbol="600000.SH",
                name="测试公司",
                themes=["测试主题"],
                stage="箱顶蓄势",
                score=90,
                box_months=18,
                box_low=20,
                box_high=30,
                box_width=0.5,
                last_close=29,
                box_position=0.9,
                monthly_slope=0.001,
                amount_contraction=0.8,
                prior_peak_multiple=1.1,
                action="等待突破确认。",
                confirmation="放量站稳箱顶。",
                invalidation="跌破箱底。",
            )
        ]
    )
    card = build_feishu_card(report)
    contents = "\n".join(
        element.get("content", "")
        for element in card["body"]["elements"]
        if element.get("tag") == "markdown"
    )
    assert "月线长期箱体" in contents
    assert "20.00-30.00" in contents

    report.cross_market = CrossMarketReport(
        themes=[
            CrossMarketThemeSignal(
                theme="创新药",
                status="A港共振",
                score=90,
                hk_members=13,
                hk_breadth_5d=1,
                hk_breadth_20d=0.8,
                hk_avg_ret_5d=0.08,
                hk_avg_ret_20d=0.2,
                hk_amount_heat=1.1,
                a_share_rank=1,
                a_share_status="主线成立",
                action="保持观察。",
            )
        ],
        ah_pairs=[],
    )
    card = build_feishu_card(report)
    contents = "\n".join(
        element.get("content", "") for element in card["body"]["elements"] if element.get("tag") == "markdown"
    )
    assert "A/H联动确认" in contents
    assert "创新药｜A港共振" in contents


def test_card_appends_dashboard_button_when_url_configured() -> None:
    report = RadarReport(
        generated_at="2026-06-29T00:00:00+00:00",
        data_as_of="2026-06-26",
        mode="curated",
        universe="CN_Equity_A",
        scanned_symbols=0,
        data_source="test",
        themes=[],
        market_pulses=[],
        market_structure=_market_structure(),
        trading_gate=_green_gate(),
        strong_stocks=StrongStockReport(selected_themes=[], hold_days=5, candidates=[]),
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
    )

    without_url = build_feishu_card(report)
    assert all(element.get("tag") != "button" for element in without_url["body"]["elements"])

    url = "https://ashare-mainline-radar-dashboard.vercel.app"
    with_url = build_feishu_card(report, dashboard_url=f"  {url}  ")
    button = with_url["body"]["elements"][-1]
    assert button["tag"] == "button"
    assert button["text"]["content"] == "打开完整作战台"
    assert button["behaviors"][0]["type"] == "open_url"
    assert button["behaviors"][0]["default_url"] == url
    assert with_url["body"]["elements"][-2]["tag"] == "hr"


def test_normalize_dashboard_url_rejects_non_http() -> None:
    assert _normalize_dashboard_url(None) is None
    assert _normalize_dashboard_url("   ") is None
    with pytest.raises(ValueError, match="http"):
        _normalize_dashboard_url("javascript:alert(1)")


def test_write_feishu_status(tmp_path) -> None:
    path = write_feishu_status(
        tmp_path / "status.json", FeishuStatus(status="failed", code=19007, message="Bot Not Enabled")
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["code"] == 19007


def test_target_text_explains_valuation_style_cap() -> None:
    target = TargetPriceEstimate(
        symbol="000933.SZ",
        name="神火股份",
        theme="有色金属与铜",
        candidate_type="低位资金介入",
        basis="压力位修复目标",
        horizon="4-12周观察目标",
        last_close=25.35,
        target_low=29.15,
        target_high=31.56,
        upside_low=0.15,
        upside_high=0.245,
        stop_price=23.8,
        downside_to_stop=-0.061,
        reward_risk_low=2.46,
        reward_risk_high=4.02,
        confidence="中",
        evidence=["估值风格代理：周期，目标上沿约束 25%"],
    )

    text = _target_text(target)

    assert "估值：周期｜上沿约25%" in text


def test_sell_the_news_risk_is_not_a_hold_candidate() -> None:
    candidate = StrongStockCandidate(
        symbol="600000.SH",
        name="测试公司",
        theme="AI算力",
        last_close=20,
        score=90,
        status="趋势延续",
        ret_5d=0.05,
        ret_20d=0.18,
        amount_ratio=1.2,
        high_proximity_20d=-0.03,
        fundamental_status="基本面兑现",
        expectation_status="利好兑现风险",
        backtest=BacktestSummary(
            symbol="600000.SH",
            name="测试公司",
            theme="AI算力",
            hold_days=15,
            signals=8,
            win_rate=0.75,
            avg_return=0.08,
            median_return=0.06,
            best_return=0.20,
            worst_return=-0.05,
            avg_max_drawdown=-0.04,
        ),
    )

    assert _hold_ready(candidate, "半山腰兑现") is False


def test_crowded_high_without_earnings_support_is_not_a_hold_candidate() -> None:
    candidate = StrongStockCandidate(
        symbol="600000.SH",
        name="测试公司",
        theme="AI算力",
        last_close=20,
        score=90,
        status="趋势延续",
        ret_5d=0.05,
        ret_20d=0.18,
        amount_ratio=1.2,
        high_proximity_20d=-0.03,
        fundamental_status="基本面兑现",
        backtest=BacktestSummary(
            symbol="600000.SH",
            name="测试公司",
            theme="AI算力",
            hold_days=15,
            signals=8,
            win_rate=0.75,
            avg_return=0.08,
            median_return=0.06,
            best_return=0.20,
            worst_return=-0.05,
            avg_max_drawdown=-0.04,
        ),
    )

    assert _hold_ready(candidate, "山顶高拥挤") is False
    assert _hold_ready(candidate, "山顶高拥挤·业绩支撑") is True


def test_uncovered_company_is_not_a_hold_candidate() -> None:
    candidate = StrongStockCandidate(
        symbol="600000.SH",
        name="测试公司",
        theme="AI算力",
        last_close=20,
        score=90,
        status="趋势延续",
        ret_5d=0.05,
        ret_20d=0.18,
        amount_ratio=1.2,
        high_proximity_20d=-0.03,
        fundamental_status="未覆盖",
        backtest=BacktestSummary(
            symbol="600000.SH",
            name="测试公司",
            theme="AI算力",
            hold_days=15,
            signals=8,
            win_rate=0.75,
            avg_return=0.08,
            median_return=0.06,
            best_return=0.20,
            worst_return=-0.05,
            avg_max_drawdown=-0.04,
        ),
    )

    assert _hold_ready(candidate, "半山腰待验证") is False
    candidate.name = "人工智能ETF"
    assert _hold_ready(candidate, "半山腰待验证") is True


def test_red_gate_waiting_note_does_not_suggest_trial_position() -> None:
    plan = NextBuyPlan(
        symbol="600000.SH",
        name="测试公司",
        theme="AI算力",
        decision="优先候选，分批确认",
        priority_score=85,
        last_close=20,
        entry_plan="可用小仓试探。",
        invalidation="跌破退出。",
        position_note="首笔试错。",
    )

    note = _waiting_note(plan, "red")

    assert "仅观察" in note
    assert "小仓试探" not in note


def test_uncovered_company_waiting_note_requires_fundamental_data() -> None:
    plan = NextBuyPlan(
        symbol="600000.SH",
        name="测试公司",
        theme="AI算力",
        decision="优先候选，分批确认",
        priority_score=85,
        last_close=20,
        entry_plan="等待回踩确认。",
        invalidation="跌破退出。",
        position_note="首笔试错。",
    )
    candidate = StrongStockCandidate(
        symbol=plan.symbol,
        name=plan.name,
        theme=plan.theme,
        last_close=20,
        score=85,
        status="趋势延续",
        ret_5d=0.05,
        ret_20d=0.18,
        amount_ratio=1.2,
        high_proximity_20d=-0.03,
        fundamental_status="未覆盖",
    )

    note = _waiting_note(plan, "green", candidate)

    assert "基本面未覆盖" in note
    assert "不进入尝试建仓" in note


def test_card_allows_etf_attempt_without_company_fundamentals() -> None:
    candidate = StrongStockCandidate(
        symbol="588200.SH",
        name="科创芯片ETF嘉实",
        theme="半导体国产替代",
        last_close=1.2,
        score=85,
        status="突破观察",
        ret_5d=0.05,
        ret_20d=0.12,
        amount_ratio=1.2,
        high_proximity_20d=-0.02,
        backtest=BacktestSummary(
            symbol="588200.SH",
            name="科创芯片ETF嘉实",
            theme="半导体国产替代",
            hold_days=15,
            signals=6,
            win_rate=0.67,
            avg_return=0.05,
            median_return=0.04,
            best_return=0.12,
            worst_return=-0.04,
            avg_max_drawdown=-0.03,
        ),
    )
    plan = NextBuyPlan(
        symbol=candidate.symbol,
        name=candidate.name,
        theme=candidate.theme,
        decision="突破确认候选",
        priority_score=82,
        last_close=1.2,
        entry_plan="放量站上1.22后确认。",
        invalidation="跌破1.12退出。",
        position_note="首笔试错。",
    )
    report = RadarReport(
        generated_at="2026-07-11T00:00:00+00:00",
        data_as_of="2026-07-10",
        mode="universe",
        universe="CN_Equity_A",
        scanned_symbols=1200,
        data_source="test",
        themes=[],
        market_pulses=[],
        market_structure=_market_structure(),
        trading_gate=_green_gate(),
        strong_stocks=StrongStockReport(selected_themes=[candidate.theme], hold_days=15, candidates=[candidate]),
        next_buy=NextBuyReport(primary=plan),
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
    )
    card = build_feishu_card(report)
    contents = "\n".join(
        element.get("content", "") for element in card["body"]["elements"] if element.get("tag") == "markdown"
    )
    assert "科创芯片ETF嘉实" in contents
    assert "ETF分散载体" in contents
    assert "15日回测" in contents


def test_red_gate_suppresses_attempt_section() -> None:
    report = RadarReport(
        generated_at="2026-07-13T00:00:00+00:00",
        data_as_of="2026-07-13",
        mode="universe",
        universe="CN_Equity_A",
        scanned_symbols=1200,
        data_source="test",
        themes=[],
        market_pulses=[],
        market_structure=MarketStructure(
            status="破位确认",
            score=0,
            index_count=3,
            above_ma5_ratio=0.33,
            above_ma20_ratio=0,
            bullish_alignment_ratio=0,
            volume_confirmation_ratio=0,
            higher_high_low_ratio=0,
            confirmed_breakdown_ratio=1,
            evidence=["站上20日线指数 0%", "连续3日跌破20日线指数 100%"],
        ),
        trading_gate=TradingGate(
            "red",
            "暂停新仓",
            16.3,
            0,
            [
                "硬熔断：指数结构破位确认，连续3日跌破20日线指数 100%；个股反弹再猛也不新开仓，直到多数指数收复20日线",
                "三大指数单日中位涨跌 2.21%",
                "扫描股票上涨占比 84.6%，跌超2%占比 2.8%",
            ],
            ["观察黄金坑"],
        ),
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
    )

    card = build_feishu_card(report)
    contents = "\n".join(
        element.get("content", "") for element in card["body"]["elements"] if element.get("tag") == "markdown"
    )

    assert "今日交易状态：暂停新仓" in contents
    assert "关闭原因" in contents
    assert "硬熔断：指数结构破位确认" in contents
    assert "结构证据" in contents
    assert "连续3日跌破20日线指数 100%" in contents
    assert "解锁条件" in contents
    assert "市场风险闸门已关闭" in contents
    assert "已有仓位：仅留强去弱" in contents


def test_card_keeps_lifecycle_alert_when_gate_is_red() -> None:
    report = RadarReport(
        generated_at="2026-07-13T00:00:00+00:00",
        data_as_of="2026-07-13",
        mode="universe",
        universe="CN_Equity_A",
        scanned_symbols=1200,
        data_source="test",
        themes=[],
        market_pulses=[],
        market_structure=_market_structure(),
        trading_gate=TradingGate("red", "暂停新仓", 24, 0, ["三大指数大跌"], ["观察主线"]),
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
        theme_lifecycle=ThemeLifecycleReport(
            history_days=45,
            signals=[
                ThemeLifecycleSignal(
                    theme="创新药",
                    stage="主线回踩",
                    score=91,
                    current_status="轮动观察",
                    started_at="2026-06-23",
                    confirmed_at="2026-06-30",
                    stage_since="2026-07-13",
                    previous_stage="主线延续",
                    transition_age=0,
                    breadth_5d=0.1,
                    breadth_20d=0.8,
                    avg_ret_5d=-0.03,
                    avg_ret_20d=0.12,
                    amount_heat=0.96,
                    action="等待止跌确认。",
                )
            ],
        ),
    )

    card = build_feishu_card(report)
    contents = "\n".join(
        element.get("content", "") for element in card["body"]["elements"] if element.get("tag") == "markdown"
    )

    assert "创新药｜主线回踩" in contents
    assert "启动 2026-06-23" in contents
    assert "交易闸门关闭：保留主线预警" in contents


def test_card_separates_mainline_rank_from_lifecycle_transition_order() -> None:
    report = RadarReport(
        generated_at="2026-07-16T00:00:00+00:00",
        data_as_of="2026-07-15",
        mode="universe",
        universe="CN_Equity_A",
        scanned_symbols=1200,
        data_source="test",
        themes=[
            ThemeSnapshot("创新药", 100, "主线成立", 10, 1, 1, 0.1, 0.3, 0.9, 0, []),
            ThemeSnapshot("券商金融", 83, "主线成立", 10, 0.8, 0.9, 0.02, 0.04, 0.7, 0, []),
            ThemeSnapshot("AI算力", 73, "主线候选", 10, 0.3, 0.7, -0.01, 0.1, 1.1, 0, []),
        ],
        market_pulses=[],
        market_structure=_market_structure(),
        trading_gate=_green_gate(),
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
        theme_lifecycle=ThemeLifecycleReport(
            history_days=45,
            signals=[
                ThemeLifecycleSignal(
                    theme="AI算力",
                    stage="主线回踩",
                    score=73,
                    current_status="主线候选",
                    started_at="2026-07-09",
                    confirmed_at="2026-07-09",
                    stage_since="2026-07-15",
                    previous_stage="主线延续",
                    transition_age=0,
                    breadth_5d=0.3,
                    breadth_20d=0.7,
                    avg_ret_5d=-0.01,
                    avg_ret_20d=0.1,
                    amount_heat=1.1,
                    action="等待止跌",
                ),
                ThemeLifecycleSignal(
                    theme="创新药",
                    stage="主线延续",
                    score=100,
                    current_status="主线成立",
                    started_at="2026-06-23",
                    confirmed_at="2026-06-29",
                    stage_since="2026-07-14",
                    previous_stage="主升加速",
                    transition_age=1,
                    breadth_5d=1,
                    breadth_20d=1,
                    avg_ret_5d=0.1,
                    avg_ret_20d=0.3,
                    amount_heat=0.9,
                    action="等待回踩",
                ),
            ],
        ),
    )

    card = build_feishu_card(report)
    contents = "\n".join(
        element.get("content", "") for element in card["body"]["elements"] if element.get("tag") == "markdown"
    )

    assert "当前主线排名" in contents
    assert "1. 创新药" in contents
    assert "2. 券商金融" in contents
    assert "第1主线｜创新药｜主线延续" in contents
    assert "第3主线｜AI算力｜主线回踩" in contents
    assert contents.index("第1主线｜创新药") < contents.index("第3主线｜AI算力")
