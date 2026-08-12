import json
from urllib.error import HTTPError

from ashare_mainline_radar.storage import ACTIONABLE_ROLES, build_storage_bundle, persist_report


def _report() -> dict:
    return {
        "generated_at": "2026-07-17T08:50:00+00:00",
        "data_as_of": "2026-07-17",
        "mode": "universe",
        "universe": "CN_Equity_A",
        "scanned_symbols": 5552,
        "themes": [{"name": "创新药", "status": "主线成立", "score": 92.0}],
        "theme_lifecycle": {"signals": [{"theme": "创新药", "stage": "主升加速"}]},
        "trading_gate": {"level": "yellow", "state": "只准试错仓", "score": 52.0},
        "market_structure": {"status": "震荡"},
        "strong_stocks": {
            "candidates": [
                {
                    "symbol": "300122.SZ",
                    "name": "智飞生物",
                    "theme": "创新药",
                    "last_close": 35.0,
                    "score": 88.0,
                    "status": "趋势延续",
                    "ret_20d": 0.12,
                }
            ]
        },
        "next_buy": {
            "primary": {
                "symbol": "300122.SZ",
                "name": "智飞生物",
                "theme": "创新药",
                "last_close": 35.0,
                "priority_score": 94.0,
                "decision": "等待回踩",
                "entry_plan": "回踩不破后分批",
                "invalidation": "跌破箱底",
                "execution_status": "watching",
                "entry_mode": "pullback_close_reclaim",
                "entry_zone_low": 33.43,
                "entry_zone_high": 34.48,
                "confirm_price": 35.42,
                "stop_price": 32.20,
                "valid_for_days": 5,
                "max_hold_days": 15,
                "max_position_fraction": 0.25,
                "initial_position_fraction": 1 / 12,
            },
            "alternatives": [],
            "by_theme": [],
        },
        "golden_pits": {"candidates": []},
        "accumulation": {"candidates": []},
        "monthly_bases": {"candidates": []},
        "expectation_gaps": {
            "signals": [
                {
                    "symbol": "300122.SZ",
                    "name": "智飞生物",
                    "status": "业绩价格共振",
                    "score": 85.0,
                    "announce_date": "2026-07-10",
                },
                {
                    "symbol": "600519.SH",
                    "name": "预期差仅扫描样例",
                    "status": "预期差未确认",
                    "score": 50.0,
                    "announce_date": "2026-07-01",
                },
            ]
        },
        "leader_tape": [
            {
                "symbol": "000001.SZ",
                "name": "领涨磁带样例",
                "theme": "银行",
                "last_close": 11.0,
                "ret_5d": 0.08,
            }
        ],
        "market_watchlist": [
            {
                "symbol": "510300.SH",
                "name": "沪深300ETF",
                "theme": "市场观察",
                "last_close": 4.0,
            }
        ],
        "unmapped_pullback": {
            "candidates": [
                {
                    "symbol": "600000.SH",
                    "name": "未映射回踩样例",
                    "theme": "未映射强势",
                    "style_tag": "pullback_reclaim",
                    "buyable_now": True,
                    "decision": "未映射回踩确认，可小仓试错",
                    "priority_score": 81.0,
                    "last_close": 12.0,
                    "entry_zone_low": 11.4,
                    "entry_zone_high": 11.8,
                    "confirm_price": 12.1,
                    "stop_price": 11.0,
                }
            ],
            "buyable_now": [
                {
                    "symbol": "600000.SH",
                    "name": "未映射回踩样例",
                    "theme": "未映射强势",
                    "buyable_now": True,
                    "last_close": 12.0,
                    "entry_zone_low": 11.4,
                    "entry_zone_high": 11.8,
                    "confirm_price": 12.1,
                    "stop_price": 11.0,
                }
            ],
            "scanned": 1,
            "notes": [],
        },
        "fundamentals": {"snapshots": [{"symbol": "300122.SZ", "status": "基本面兑现"}]},
        "target_prices": {"estimates": [{"symbol": "300122.SZ", "target_low": 40.0, "target_high": 45.0}]},
        "warnings": [],
        "cross_market": {},
        "price_limit_watch": {
            "as_of": "2026-07-17",
            "limit_up_touches": 3,
            "closed_limit_up": 2,
            "first_board_closed": 1,
            "one_price_limit_up": 0,
            "broken_boards": 1,
            "ceiling_to_floor": 0,
            "limit_down_touches": 1,
            "closed_limit_down": 1,
            "one_price_limit_down": 0,
            "broken_floors": 0,
            "floor_to_ceiling": 0,
            "signals": [],
        },
        "source_statuses": [],
    }


def test_storage_bundle_merges_roles_for_each_symbol() -> None:
    bundle = build_storage_bundle(_report())

    assert bundle["run"]["run_key"] == "cn:2026-07-17:universe:CN_Equity_A"
    assert bundle["themes"][0]["lifecycle_stage"] == "主升加速"
    assert bundle["run"]["summary"]["price_limit_watch"]["closed_limit_up"] == 2
    assert len(bundle["symbols"]) == 1
    by_symbol = {item["symbol"]: item for item in bundle["symbols"]}
    symbol = by_symbol["300122.SZ"]
    assert symbol["roles"] == ["next_buy", "strong_stock", "expectation_gap"]
    assert symbol["priority_score"] == 94.0
    assert symbol["trade_plan"]["entry_plan"] == "回踩不破后分批"
    assert symbol["fundamental_payload"]["status"] == "基本面兑现"
    assert symbol["target_payload"]["target_high"] == 45.0
    assert symbol["signal_payload"]["expectation_gap"]["status"] == "业绩价格共振"
    assert "600000.SH" not in by_symbol
    assert "600519.SH" not in by_symbol
    assert "000001.SZ" not in by_symbol
    assert "510300.SH" not in by_symbol
    assert ACTIONABLE_ROLES == (
        "next_buy",
        "strong_stock",
        "golden_pit",
        "accumulation",
        "monthly_base",
    )
    assert bundle["tracking_policy"]["selection_roles"] == list(ACTIONABLE_ROLES)
    assert "expectation_gap" in bundle["tracking_policy"]["overlay_roles"]
    assert "leader_tape" in bundle["tracking_policy"]["artifact_only_roles"]
    assert "market_watchlist" in bundle["tracking_policy"]["artifact_only_roles"]
    assert "unmapped_pullback" not in bundle["tracking_policy"]["selection_roles"]
    assert len(bundle["trade_plans"]) == 2
    next_buy_plans = [item for item in bundle["trade_plans"] if item["symbol"] == "300122.SZ"]
    assert next_buy_plans[0]["plan_key"] == "2026-07-17:300122.SZ:mainline-v1-theme-exit-2d"
    assert next_buy_plans[0]["theme_exit_days"] == 2
    assert next_buy_plans[0]["source_role"] == "next_buy"
    assert next_buy_plans[1]["is_shadow"] is True
    assert next_buy_plans[1]["theme_exit_days"] == 3
    assert all(item["source_role"] != "unmapped_pullback" for item in bundle["trade_plans"])
    assert bundle["trade_events"][0]["event_type"] == "created"


def test_storage_skips_non_actionable_bulk_lists() -> None:
    report = _report()
    report["expectation_gaps"]["signals"].extend(
        {
            "symbol": f"60{idx:04d}.SH",
            "name": f"bulk-{idx}",
            "status": "预期差未确认",
            "score": 50.0,
        }
        for idx in range(200)
    )
    report["leader_tape"] = [
        {"symbol": f"00{idx:04d}.SZ", "name": f"tape-{idx}", "last_close": 10.0} for idx in range(25)
    ]
    report["market_watchlist"] = [
        {"symbol": f"51{idx:04d}.SH", "name": f"watch-{idx}", "last_close": 1.0} for idx in range(13)
    ]

    bundle = build_storage_bundle(report)
    symbols = {item["symbol"] for item in bundle["symbols"]}

    assert symbols == {"300122.SZ"}
    assert all(not item.startswith("60") or item == "300122.SZ" for item in symbols)
    assert not any(item.startswith("00") for item in symbols)
    assert not any(item.startswith("51") for item in symbols)


def test_artifact_backend_writes_portable_bundle_and_status(tmp_path) -> None:
    status = persist_report(_report(), tmp_path, backend="artifact")

    assert status.status == "deferred"
    assert status.symbol_records == 1
    bundle = json.loads((tmp_path / "storage_bundle.json").read_text(encoding="utf-8"))
    persisted_status = json.loads((tmp_path / "storage_status.json").read_text(encoding="utf-8"))
    assert bundle["schema_version"] == "radar-storage-v4"
    assert bundle["tracking_policy"]["first_selected_price_source"] == "symbol_snapshot.last_close"
    assert persisted_status["backend"] == "artifact"


def test_publishable_key_uses_scoped_ingest_header(tmp_path) -> None:
    requests = []

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"[]"

    def opener(request, timeout):
        requests.append((request, timeout))
        return Response()

    status = persist_report(
        _report(),
        tmp_path,
        backend="supabase",
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="private-ingest-key",
        opener=opener,
    )

    assert status.status == "stored"
    assert len(requests) == 6
    assert requests[0][0].get_header("Apikey") == "sb_publishable_test"
    assert requests[0][0].get_header("X-radar-ingest-key") == "private-ingest-key"
    assert requests[0][0].get_header("Authorization") is None


def test_supabase_http_error_body_is_captured_in_storage_status(tmp_path) -> None:
    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"[]"

    def opener(request, timeout):
        if request.full_url.startswith("https://example.supabase.co/rest/v1/radar_symbol_snapshots"):
            raise HTTPError(
                request.full_url,
                400,
                "Bad Request",
                hdrs=None,
                fp=__import__("io").BytesIO(b'{"code":"PGRST102","message":"Empty or invalid json"}'),
            )
        return Response()

    status = persist_report(
        _report(),
        tmp_path,
        backend="supabase",
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="private-ingest-key",
        opener=opener,
    )

    persisted_status = json.loads((tmp_path / "storage_status.json").read_text(encoding="utf-8"))
    assert status.status == "failed"
    assert persisted_status["status"] == "failed"
    assert "HTTP 400" in persisted_status["message"]
    assert "Empty or invalid json" in persisted_status["message"]
    assert persisted_status["symbol_records"] == 1


def test_existing_production_plan_does_not_block_shadow_plan(tmp_path) -> None:
    requests = []

    class Response:
        status = 204

        def __init__(self, payload=b"[]"):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return self.payload

    def opener(request, timeout):
        requests.append((request, timeout))
        if request.full_url.startswith("https://example.supabase.co/rest/v1/radar_trade_plans?") and request.data is None:
            existing = [
                {
                    "plan_key": "2026-07-16:300122.SZ:mainline-v1-theme-exit-2d",
                    "symbol": "300122.SZ",
                    "strategy_version": "mainline-v1-theme-exit-2d",
                    "status": "open",
                }
            ]
            return Response(json.dumps(existing).encode("utf-8"))
        return Response()

    status = persist_report(
        _report(),
        tmp_path,
        backend="supabase",
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="private-ingest-key",
        opener=opener,
    )

    assert status.status == "stored"
    plan_request = next(
        request
        for request, _timeout in requests
        if request.full_url.startswith("https://example.supabase.co/rest/v1/radar_trade_plans?")
        and request.data is not None
    )
    plans = json.loads(plan_request.data.decode("utf-8"))
    assert ("300122.SZ", "mainline-v1-theme-exit-2d") not in {
        (plan["symbol"], plan["strategy_version"]) for plan in plans
    }
    assert ("300122.SZ", "mainline-v2-theme-exit-3d-frozen-20260718") in {
        (plan["symbol"], plan["strategy_version"]) for plan in plans
    }
    assert all(plan["symbol"] != "600000.SH" for plan in plans)
    assert all(plan.get("source_role") != "unmapped_pullback" for plan in plans)

    event_request = next(
        request
        for request, _timeout in requests
        if request.full_url.startswith("https://example.supabase.co/rest/v1/radar_trade_events?")
    )
    events = json.loads(event_request.data.decode("utf-8"))
    assert ("300122.SZ", "mainline-v2-theme-exit-3d-frozen-20260718") in {
        (event["symbol"], event["strategy_version"]) for event in events
    }
