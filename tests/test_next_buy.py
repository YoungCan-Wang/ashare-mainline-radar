from ashare_mainline_radar.models import (
    BacktestSummary,
    NextBuyPlan,
    NextBuyReport,
    StrongStockCandidate,
    ThemeBuyGroup,
    ThemeLifecycleReport,
    ThemeLifecycleSignal,
    ThemeSnapshot,
    TradingGate,
)
from ashare_mainline_radar.next_buy import build_next_buy_report, overlay_triggered_working_orders


def test_build_next_buy_report_selects_primary() -> None:
    candidate = StrongStockCandidate(
        symbol="002747.SZ",
        name="埃斯顿",
        theme="机器人",
        last_close=20.0,
        score=95.0,
        status="主升确认",
        ret_5d=0.08,
        ret_20d=0.25,
        amount_ratio=1.4,
        high_proximity_20d=-0.02,
        fundamental_status="基本面兑现",
        backtest=BacktestSummary(
            symbol="002747.SZ",
            name="埃斯顿",
            theme="机器人",
            hold_days=5,
            signals=8,
            win_rate=0.625,
            avg_return=0.04,
            median_return=0.03,
            best_return=0.12,
            worst_return=-0.05,
            avg_max_drawdown=-0.03,
        ),
    )
    themes = [
        ThemeSnapshot(
            name="机器人",
            score=92.0,
            status="主线成立",
            members=10,
            breadth_5d=0.7,
            breadth_20d=0.8,
            avg_ret_5d=0.05,
            avg_ret_20d=0.15,
            amount_heat=1.2,
            catalyst_count=0,
            leaders=[],
        )
    ]
    report = build_next_buy_report([candidate], themes, [])
    assert report.primary is not None
    assert report.primary.symbol == "002747.SZ"
    assert "失效" not in report.primary.decision
    assert report.by_theme
    assert report.by_theme[0].theme == "机器人"
    assert report.by_theme[0].plans[0].symbol == "002747.SZ"
    assert "按5个交易日波段处理" in report.primary.position_note
    assert "已有浮盈" in report.primary.position_note
    assert "亏损中不补仓" not in report.primary.position_note
    assert "跌破失效位不补仓" in report.primary.position_note


def test_red_gate_suppresses_new_buy_but_keeps_waiting_candidates() -> None:
    candidate = StrongStockCandidate(
        symbol="002747.SZ",
        name="埃斯顿",
        theme="机器人",
        last_close=20.0,
        score=90.0,
        status="趋势延续",
        ret_5d=0.05,
        ret_20d=0.18,
        amount_ratio=1.2,
        high_proximity_20d=-0.04,
    )
    theme = ThemeSnapshot(
        name="机器人",
        score=88,
        status="主线成立",
        members=8,
        breadth_5d=0.6,
        breadth_20d=0.8,
        avg_ret_5d=0.03,
        avg_ret_20d=0.12,
        amount_heat=1.1,
        catalyst_count=0,
        leaders=[],
    )
    gate = TradingGate("red", "暂停新仓", 25, 0, ["三大指数大跌"], ["观察"])

    report = build_next_buy_report([candidate], [theme], [], gate)

    assert report.primary is None
    assert report.by_theme[0].plans[0].symbol == "002747.SZ"


def test_expectation_risk_stays_in_waiting_instead_of_primary() -> None:
    candidate = StrongStockCandidate(
        symbol="002747.SZ",
        name="埃斯顿",
        theme="机器人",
        last_close=20.0,
        score=95.0,
        status="趋势延续",
        ret_5d=0.05,
        ret_20d=0.20,
        amount_ratio=1.2,
        high_proximity_20d=-0.03,
        fundamental_status="基本面兑现",
        expectation_status="利好兑现风险",
    )
    theme = ThemeSnapshot("机器人", 90, "主线成立", 8, 0.7, 0.8, 0.04, 0.15, 1.2, 0, [])

    report = build_next_buy_report([candidate], [theme], [])

    assert report.primary is None
    assert report.by_theme[0].plans[0].decision == "利好兑现风险，等待筹码稳定"


def _lifecycle(stage: str, independence_status: str = "随市主线") -> ThemeLifecycleReport:
    return ThemeLifecycleReport(
        history_days=45,
        signals=[
            ThemeLifecycleSignal(
                theme="机器人",
                stage=stage,
                score=90,
                current_status="主线成立",
                started_at="2026-06-23",
                confirmed_at="2026-06-29",
                stage_since="2026-06-29",
                previous_stage="扩散启动",
                transition_age=1,
                breadth_5d=0.8,
                breadth_20d=0.7,
                avg_ret_5d=0.08,
                avg_ret_20d=0.15,
                amount_heat=1.3,
                action="按阶段执行",
                independence_status=independence_status,
            )
        ],
    )


def _candidate(ret_5d: float = 0.08) -> StrongStockCandidate:
    return StrongStockCandidate(
        symbol="002747.SZ",
        name="埃斯顿",
        theme="机器人",
        last_close=20.0,
        score=95.0,
        status="主升确认",
        ret_5d=ret_5d,
        ret_20d=0.25,
        amount_ratio=1.4,
        high_proximity_20d=-0.02,
        fundamental_status="基本面兑现",
    )


def _active_theme() -> ThemeSnapshot:
    return ThemeSnapshot("机器人", 92, "主线成立", 10, 0.8, 0.7, 0.08, 0.15, 1.3, 0, [])


def test_expansion_candidate_stays_in_waiting_until_mainline_confirmation() -> None:
    report = build_next_buy_report(
        [_candidate()],
        [_active_theme()],
        [],
        theme_lifecycle=_lifecycle("扩散启动"),
    )

    assert report.primary is None
    assert report.by_theme[0].plans[0].decision == "扩散启动，等待主线确认"
    assert report.by_theme[0].lifecycle_stage == "扩散启动"


def test_acceleration_candidate_is_actionable_only_after_chase_filter() -> None:
    report = build_next_buy_report(
        [_candidate(ret_5d=0.10)],
        [_active_theme()],
        [],
        theme_lifecycle=_lifecycle("主升加速", "逆势独立主线"),
    )

    assert report.primary is not None
    assert report.primary.decision == "主升加速，等待回踩"
    assert report.primary.independence_status == "逆势独立主线"

    hot_report = build_next_buy_report(
        [_candidate(ret_5d=0.18)],
        [_active_theme()],
        [],
        theme_lifecycle=_lifecycle("主升加速"),
    )
    assert hot_report.primary is None
    assert hot_report.by_theme[0].plans[0].decision == "主升加速，禁止追高"


def test_pullback_candidate_stops_new_position_but_remains_visible() -> None:
    report = build_next_buy_report(
        [_candidate()],
        [_active_theme()],
        [],
        theme_lifecycle=_lifecycle("主线回踩"),
    )

    assert report.primary is None
    assert report.by_theme[0].plans[0].decision == "主线回踩，等待止跌确认"


def test_active_theme_without_qualified_stock_is_still_reported() -> None:
    report = build_next_buy_report([], [_active_theme()], [], theme_lifecycle=_lifecycle("主线确认"))

    assert report.by_theme[0].theme == "机器人"
    assert report.by_theme[0].plans == []
    assert "没有个股通过" in (report.by_theme[0].note or "")


def test_uncovered_company_cannot_become_primary_plan() -> None:
    candidate = _candidate()
    candidate.fundamental_status = "未覆盖"

    report = build_next_buy_report([candidate], [_active_theme()], [])

    assert report.primary is None
    assert report.by_theme[0].plans[0].decision == "基本面未覆盖，等待财务确认"


def test_hot_uncovered_company_reports_both_chase_and_fundamental_blocks() -> None:
    candidate = _candidate(ret_5d=0.18)
    candidate.fundamental_status = "未覆盖"

    report = build_next_buy_report(
        [candidate],
        [_active_theme()],
        [],
        theme_lifecycle=_lifecycle("主升加速"),
    )

    assert report.primary is None
    assert report.by_theme[0].plans[0].decision == "主升加速，禁止追高；基本面未覆盖"


def _shanjin_watching_card() -> NextBuyPlan:
    return NextBuyPlan(
        symbol="000975.SZ",
        name="山金国际",
        theme="黄金贵金属",
        decision="主升加速，等待回踩",
        priority_score=88.0,
        last_close=29.26,
        entry_plan="未来5个交易日内，收盘站上 29.61 且当日收阳；下一交易日开盘未封涨停时执行首笔。",
        invalidation="跌破 26.92 先降级观察。",
        position_note="首笔只用计划仓位1/3。",
        execution_status="watching",
        entry_mode="breakout_close_confirm",
        entry_zone_low=27.47,
        entry_zone_high=28.33,
        confirm_price=29.61,
        stop_price=26.92,
    )


def _shanjin_triggered_plan(**overrides):
    row = {
        "plan_key": "2026-08-21:000975.SZ:mainline-v1-theme-exit-2d",
        "symbol": "000975.SZ",
        "name": "山金国际",
        "theme": "黄金贵金属",
        "signal_date": "2026-08-21",
        "status": "triggered",
        "trigger_date": "2026-08-24",
        "entry_mode": "breakout_close_confirm",
        "entry_zone_low": 27.29,
        "entry_zone_high": 28.15,
        "confirm_price": 28.92,
        "stop_price": 26.61,
        "strategy_version": "mainline-v1-theme-exit-2d",
        "is_shadow": False,
        "cost_payload": {
            "working_order": {
                "working_order_type": "market_on_open",
                "working_order_note": "次日开盘价市价挂单",
            }
        },
    }
    row.update(overrides)
    return row


def test_triggered_plan_replaces_fresh_watching_card() -> None:
    watching = _shanjin_watching_card()
    next_buy = NextBuyReport(
        primary=watching,
        alternatives=[],
        by_theme=[
            ThemeBuyGroup(
                theme="黄金贵金属",
                theme_status="主线成立",
                plans=[watching],
                lifecycle_stage="主升加速",
            )
        ],
    )

    overlay_triggered_working_orders(next_buy, [_shanjin_triggered_plan()])

    assert next_buy.primary is not None
    assert next_buy.primary.symbol == "000975.SZ"
    assert next_buy.primary.decision == "已触发"
    assert next_buy.primary.execution_status == "triggered"
    assert next_buy.primary.confirm_price == 28.92
    assert next_buy.primary.entry_zone_low == 27.29
    assert next_buy.primary.entry_zone_high == 28.15
    assert next_buy.primary.trigger_date == "2026-08-24"
    assert next_buy.primary.signal_date == "2026-08-21"
    assert next_buy.primary.last_close == 29.26
    assert "已触发" in next_buy.primary.entry_plan
    assert "次日开盘市价挂单" in next_buy.primary.entry_plan
    assert "29.61" not in next_buy.primary.entry_plan
    assert next_buy.triggered_orders[0].symbol == "000975.SZ"
    assert next_buy.by_theme[0].plans[0].decision == "已触发"


def test_filled_plan_is_not_shown_as_next_open_working_order() -> None:
    watching = _shanjin_watching_card()
    next_buy = NextBuyReport(primary=watching)
    overlay_triggered_working_orders(
        next_buy,
        [_shanjin_triggered_plan(status="open", entry_date="2026-08-25")],
    )

    assert next_buy.triggered_orders == []
    assert next_buy.primary is watching
    assert next_buy.primary.decision == "主升加速，等待回踩"
    assert next_buy.primary.confirm_price == 29.61


def test_daily_markdown_shows_triggered_working_order() -> None:
    from ashare_mainline_radar.models import (
        AccumulationReport,
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

    watching = _shanjin_watching_card()
    next_buy = NextBuyReport(
        primary=watching,
        alternatives=[],
        by_theme=[],
    )
    overlay_triggered_working_orders(next_buy, [_shanjin_triggered_plan()])
    markdown = render_markdown(
        RadarReport(
            generated_at="2026-08-24T08:00:00+00:00",
            data_as_of="2026-08-24",
            mode="universe",
            universe="CN_Equity_A",
            scanned_symbols=1,
            data_source="test",
            themes=[],
            market_pulses=[],
            market_structure=MarketStructure(
                status="右侧确认",
                score=80,
                index_count=3,
                above_ma5_ratio=1,
                above_ma20_ratio=1,
                bullish_alignment_ratio=1,
                volume_confirmation_ratio=1,
                higher_high_low_ratio=1,
                confirmed_breakdown_ratio=0,
                evidence=[],
            ),
            trading_gate=TradingGate("green", "允许寻找买点", 70, 0, [], []),
            strong_stocks=StrongStockReport(selected_themes=[], hold_days=15, candidates=[]),
            next_buy=next_buy,
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
    )

    assert "## 已触发，次日开盘挂单" in markdown
    assert "山金国际 `000975.SZ`：已触发，次日开盘市价挂单" in markdown
    assert "确认日 2026-08-24，确认价 28.92" in markdown
    assert "原买入区 27.29-28.15" in markdown
    assert "原信号日 2026-08-21" in markdown
    assert "29.61" not in markdown
