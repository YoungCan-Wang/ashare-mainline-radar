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


def test_artifact_backend_writes_portable_bundle_and_status(tmp_path) -> None:
    status = persist_report(_report(), tmp_path, backend="artifact")

    assert status.status == "deferred"
    assert status.symbol_records == 1
    bundle = json.loads((tmp_path / "storage_bundle.json").read_text(encoding="utf-8"))
    persisted_status = json.loads((tmp_path / "storage_status.json").read_text(encoding="utf-8"))
    assert bundle["schema_version"] == "radar-storage-v1"
    assert persisted_status["backend"] == "artifact"
