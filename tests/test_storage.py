import json

from ashare_mainline_radar.storage import build_storage_bundle, persist_report


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
        "expectation_gaps": {"signals": []},
        "leader_tape": [],
        "market_watchlist": [],
        "fundamentals": {"snapshots": [{"symbol": "300122.SZ", "status": "基本面兑现"}]},
        "target_prices": {"estimates": [{"symbol": "300122.SZ", "target_low": 40.0, "target_high": 45.0}]},
        "warnings": [],
        "cross_market": {},
        "source_statuses": [],
    }


def test_storage_bundle_merges_roles_for_each_symbol() -> None:
    bundle = build_storage_bundle(_report())

    assert bundle["run"]["run_key"] == "cn:2026-07-17:universe:CN_Equity_A"
    assert bundle["themes"][0]["lifecycle_stage"] == "主升加速"
    assert len(bundle["symbols"]) == 1
    symbol = bundle["symbols"][0]
    assert symbol["roles"] == ["next_buy", "strong_stock"]
    assert symbol["priority_score"] == 94.0
    assert symbol["trade_plan"]["entry_plan"] == "回踩不破后分批"
    assert symbol["fundamental_payload"]["status"] == "基本面兑现"
    assert symbol["target_payload"]["target_high"] == 45.0
    assert len(bundle["trade_plans"]) == 2
    assert bundle["trade_plans"][0]["plan_key"] == "2026-07-17:300122.SZ:mainline-v1-theme-exit-2d"
    assert bundle["trade_plans"][0]["theme_exit_days"] == 2
    assert bundle["trade_plans"][1]["is_shadow"] is True
    assert bundle["trade_plans"][1]["theme_exit_days"] == 3
    assert bundle["trade_events"][0]["event_type"] == "created"


def test_artifact_backend_writes_portable_bundle_and_status(tmp_path) -> None:
    status = persist_report(_report(), tmp_path, backend="artifact")

    assert status.status == "deferred"
    assert status.symbol_records == 1
    bundle = json.loads((tmp_path / "storage_bundle.json").read_text(encoding="utf-8"))
    persisted_status = json.loads((tmp_path / "storage_status.json").read_text(encoding="utf-8"))
    assert bundle["schema_version"] == "radar-storage-v3"
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
    assert [plan["strategy_version"] for plan in plans] == [
        "mainline-v2-theme-exit-3d-frozen-20260718"
    ]

    event_request = next(
        request
        for request, _timeout in requests
        if request.full_url.startswith("https://example.supabase.co/rest/v1/radar_trade_events?")
    )
    events = json.loads(event_request.data.decode("utf-8"))
    assert [event["strategy_version"] for event in events] == [
        "mainline-v2-theme-exit-3d-frozen-20260718"
    ]
