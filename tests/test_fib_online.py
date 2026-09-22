import json

from ashare_mainline_radar.feishu import build_feishu_card, build_shadow_feishu_card
from ashare_mainline_radar.fib_online import apply_published_fib_board, select_fib_shadow_members
from ashare_mainline_radar.models import FibProfitSpaceCandidate, FibProfitSpacePool
from ashare_mainline_radar.next_buy import select_triggered_working_orders
from ashare_mainline_radar.paper_strategies import FIB_SHADOW_STRATEGY, PRODUCTION_PAPER_STRATEGY
from ashare_mainline_radar.quotes import ACTIONABLE_ROLES as QUOTE_ROLES
from ashare_mainline_radar.shadow_account import _intents_from_paper
from ashare_mainline_radar.storage import ACTIONABLE_ROLES, build_storage_bundle
from tests.test_feishu import _report


def _candidate(**overrides) -> FibProfitSpaceCandidate:
    payload = dict(
        symbol="600000.SH",
        name="测试股份",
        rank=1,
        last_close=10.0,
        remaining_space_pct=0.12,
        valid_flag=True,
        is_st=False,
        daily_change_pct=0.012,
    )
    payload.update(overrides)
    return FibProfitSpaceCandidate(**payload)


def test_quote_roles_track_the_same_fib_selection_pool() -> None:
    assert "fib_profit_space" in ACTIONABLE_ROLES
    assert set(ACTIONABLE_ROLES) == set(QUOTE_ROLES)


def test_shadow_eligibility_is_conservative() -> None:
    names = [
        _candidate(symbol="600000.SH", name="测试股份", rank=1, remaining_space_pct=0.2),
        _candidate(symbol="000003.SZ", name="*ST测试", rank=2, remaining_space_pct=0.5, is_st=True),
        _candidate(symbol="510300.SH", name="沪深300ETF", rank=3, remaining_space_pct=0.3),
        _candidate(symbol="600001.SH", name="空间不足", rank=4, remaining_space_pct=0.079),
        _candidate(symbol="600002.SH", name="已在主池", rank=5, remaining_space_pct=0.15),
        _candidate(symbol="600003.SH", name="几何无效", rank=6, remaining_space_pct=0.2, valid_flag=False),
        _candidate(symbol="600004.SH", name="第二合格", rank=7, remaining_space_pct=0.09),
    ]
    chosen = select_fib_shadow_members(names, gate_level="yellow", occupied_symbols={"600002.SH"})
    assert [item.symbol for item in chosen] == ["600000.SH", "600004.SH"]
    assert chosen[0].entry_mode == "pullback_close_reclaim"
    assert chosen[0].max_position_fraction == 0.12
    assert select_fib_shadow_members(names, gate_level="red", occupied_symbols=set()) == []


def test_storage_writes_fib_shadow_plan_without_production_strategy() -> None:
    report = {
        "generated_at": "2026-07-17T08:00:00+00:00",
        "data_as_of": "2026-07-17",
        "mode": "universe",
        "universe": "CN_Equity_A",
        "themes": [],
        "trading_gate": {"level": "yellow", "state": "只准试错仓"},
        "next_buy": {"primary": None, "alternatives": []},
        "fib_profit_space": {
            "state": "成功",
            "candidates": [
                {
                    "symbol": "600001.SH",
                    "name": "榜上股份",
                    "last_close": 10.0,
                    "priority_score": 20.0,
                    "score": 20.0,
                    "remaining_space_pct": 0.2,
                    "rank": 1,
                    "valid_flag": True,
                    "daily_change_pct": 0.012,
                }
            ],
            "shadow_candidates": [
                {
                    "symbol": "600001.SH",
                    "name": "榜上股份",
                    "theme": "斐波那契赚钱空间",
                    "last_close": 10.0,
                    "entry_mode": "pullback_close_reclaim",
                    "entry_zone_low": 9.55,
                    "entry_zone_high": 9.85,
                    "confirm_price": 10.12,
                    "stop_price": 9.2,
                    "execution_status": "watching",
                    "decision": "赚钱空间观察，等待回踩",
                    "valid_for_days": 5,
                    "max_hold_days": 15,
                    "max_position_fraction": 0.12,
                    "initial_position_fraction": 0.04,
                    "priority_score": 20.0,
                    "daily_change_pct": 0.012,
                }
            ],
        },
    }
    bundle = build_storage_bundle(report)
    assert bundle["symbols"][0]["roles"] == ["fib_profit_space"]
    assert bundle["symbols"][0]["market_metrics"]["daily_change_pct"] == 0.012
    assert len(bundle["trade_plans"]) == 1
    plan = bundle["trade_plans"][0]
    assert plan["strategy_version"] == FIB_SHADOW_STRATEGY.version
    assert plan["is_shadow"] is True
    assert plan["theme_exit_days"] == 0
    assert plan["strategy_version"] != PRODUCTION_PAPER_STRATEGY.version
    assert "source_role" not in plan
    assert "source_role" not in bundle["trade_events"][0]["payload"]


def test_shadow_book_accepts_fib_events_and_dedupes_production() -> None:
    frozen = "mainline-v2-theme-exit-3d-frozen-20260718"
    events = [
        {
            "symbol": "600000.SH",
            "event_type": "opened",
            "strategy_version": FIB_SHADOW_STRATEGY.version,
            "price": 11,
            "payload": {},
        },
        {
            "symbol": "600000.SH",
            "event_type": "opened",
            "strategy_version": PRODUCTION_PAPER_STRATEGY.version,
            "price": 10,
            "payload": {"name": "主池"},
        },
        {
            "symbol": "600001.SH",
            "event_type": "opened",
            "strategy_version": FIB_SHADOW_STRATEGY.version,
            "price": 8,
            "payload": {"name": "空间股"},
        },
        {
            "symbol": "600002.SH",
            "event_type": "opened",
            "strategy_version": frozen,
            "price": 9,
            "payload": {},
        },
    ]
    buys, sells = _intents_from_paper(events, [], [])
    assert sells == []
    assert [item["symbol"] for item in buys] == ["600000.SH", "600001.SH"]
    assert buys[0]["raw_price"] == 10
    assert buys[0]["name"] == "主池"


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_published_success_board_replaces_the_daily_slice() -> None:
    report = _report(
        fib_profit_space=FibProfitSpacePool(
            state="成功",
            as_of="2026-07-10",
            source="daily_klines",
            scanned=3,
            candidates=[_candidate(symbol="000001.SZ", name="日报临时", daily_change_pct=0.021)],
        )
    )

    def opener(request, timeout=30):
        url = request.full_url
        if "fib_profit_space_run_status" in url:
            assert "asof_date=eq.2026-07-10" in url
            return _Response([{"asof_date": "2026-07-10", "status": "成功", "symbol_count": 80}])
        if "fib_profit_space_daily" in url:
            return _Response(
                [
                    {
                        "code": "600000.SH",
                        "name": "测试股份",
                        "rank": 1,
                        "close": 10,
                        "remaining_space_pct": 0.12,
                        "full_box_pct": 0.2,
                        "valid_flag": True,
                        "is_st": False,
                        "lower_source": "fib_0382",
                    }
                ]
            )
        raise AssertionError(url)

    apply_published_fib_board(
        report,
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="ingest",
        opener=opener,
    )
    assert report.fib_profit_space.source == "published_board"
    assert report.fib_profit_space.candidates[0].symbol == "600000.SH"
    assert report.fib_profit_space.shadow_candidates[0].symbol == "600000.SH"

    def unrun(request, timeout=30):
        if "run_status" in request.full_url:
            return _Response([{"asof_date": "2026-07-10", "status": "未运行"}])
        return _Response([])

    report.fib_profit_space.source = "daily_klines"
    apply_published_fib_board(
        report,
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="ingest",
        opener=unrun,
    )
    assert report.fib_profit_space.source == "daily_klines"


def test_fib_triggered_orders_stay_off_the_mainline_card() -> None:
    fib = {
        "symbol": "600001.SH",
        "name": "空间股",
        "status": "triggered",
        "strategy_version": FIB_SHADOW_STRATEGY.version,
        "is_shadow": True,
    }
    production = {
        "symbol": "600000.SH",
        "name": "主池",
        "status": "triggered",
        "strategy_version": PRODUCTION_PAPER_STRATEGY.version,
        "is_shadow": False,
    }
    assert [item["symbol"] for item in select_triggered_working_orders([fib, production])] == ["600000.SH"]
    assert [item["symbol"] for item in select_triggered_working_orders([fib, production], include_fib_shadow=True)] == [
        "600001.SH",
        "600000.SH",
    ]


def test_cards_show_same_day_change_for_fib_and_shadow_names() -> None:
    report = _report(
        fib_profit_space=FibProfitSpacePool(
            state="成功",
            as_of="2026-07-10",
            source="daily_klines",
            scanned=10,
            candidates=[_candidate()],
            shadow_candidates=[_candidate()],
            notes=["影子观察"],
        )
    )
    card = build_feishu_card(report, daily_changes={"600000.SH": 0.012})
    text = "\n".join(
        element.get("content", "") for element in card["body"]["elements"] if element.get("tag") == "markdown"
    )
    assert "斐波那契赚钱空间" in text
    assert "600000.SH" in text
    assert "当日 +1.20%" in text
    assert "影子池" in text

    shadow = build_shadow_feishu_card(
        {
            "as_of": "2026-07-10",
            "account": {"equity": 100000, "cash": 100000, "market_value": 0, "initial_capital": 100000},
            "positions": [{"symbol": "600000.SH", "name": "测试股份", "shares": 100, "avg_cost": 10, "last_mark": 10.12, "sellable_shares": 0}],
            "today_events": [],
        },
        daily_changes={"600000.SH": -0.021},
    )
    shadow_text = "\n".join(
        element.get("content", "") for element in shadow["body"]["elements"] if element.get("tag") == "markdown"
    )
    assert "当日 -2.10%" in shadow_text
