import json

import pytest

from ashare_mainline_radar.dashboard import build_dashboard_payload, fetch_dashboard_history, write_dashboard


def _bundle() -> dict:
    return {
        "run": {
            "run_key": "cn:2026-07-17:universe:CN_Equity_A",
            "market_date": "2026-07-17",
            "generated_at": "2026-07-17T09:00:00+00:00",
            "top_theme": "创新药",
            "summary": {"price_limit_watch": {"limit_up_touches": 3, "broken_boards": 1, "ceiling_verdict": "关闭追板通道"}},
        },
        "themes": [
            {
                "run_key": "cn:2026-07-17:universe:CN_Equity_A",
                "market_date": "2026-07-17",
                "theme": "创新药",
                "rank": 1,
                "score": 92,
            }
        ],
        "symbols": [
            {
                "run_key": "cn:2026-07-17:universe:CN_Equity_A",
                "market_date": "2026-07-17",
                "symbol": "300122.SZ",
                "name": "智飞生物",
                "priority_score": 90,
            }
        ],
    }


def test_dashboard_payload_merges_local_run_over_remote() -> None:
    history = {
        "runs": [{"run_key": "cn:2026-07-17:universe:CN_Equity_A", "top_theme": "旧值"}],
        "themes": [],
        "symbols": [],
        "selections": [
            {
                "symbol": "300122.SZ",
                "first_selected_at": "2026-07-16T08:45:00+00:00",
                "first_market_date": "2026-07-16",
                "first_selected_price": 35.0,
            }
        ],
        "quotes": [
            {
                "symbol": "300122.SZ",
                "latest_price": 38.5,
                "daily_change_pct": 0.03,
                "quote_at": "2026-07-17T07:00:00+00:00",
                "refreshed_at": "2026-07-17T07:01:00+00:00",
            }
        ],
        "trade_plans": [
            {
                "plan_key": "2026-07-17:300122.SZ",
                "symbol": "300122.SZ",
                "status": "open",
                "entry_price": 36.0,
            },
            {
                "plan_key": "2026-07-17:300122.SZ:mainline-v2-theme-exit-3d-frozen-20260718",
                "symbol": "300122.SZ",
                "status": "open",
                "entry_price": 36.0,
                "net_return": 0.05,
                "strategy_version": "mainline-v2-theme-exit-3d-frozen-20260718",
                "is_shadow": True,
            },
        ],
    }

    payload = build_dashboard_payload(_bundle(), history)

    assert payload["current_run_key"] == "cn:2026-07-17:universe:CN_Equity_A"
    assert payload["runs"][0]["top_theme"] == "创新药"
    assert payload["runs"][0]["summary"]["price_limit_watch"]["broken_boards"] == 1
    assert payload["runs"][0]["summary"]["price_limit_watch"]["ceiling_verdict"] == "关闭追板通道"
    assert payload["themes"][0]["theme"] == "创新药"
    assert payload["symbols"][0]["symbol"] == "300122.SZ"
    assert payload["symbols"][0]["first_selected_price"] == 35.0
    assert payload["symbols"][0]["latest_price"] == 38.5
    assert payload["symbols"][0]["return_since_selection"] == pytest.approx(0.1)
    assert payload["symbols"][0]["paper_trade_plan"]["status"] == "open"
    assert payload["symbols"][0]["shadow_trade_plan"]["net_return"] == 0.05


def test_fetch_dashboard_history_paginates_and_scopes_requests() -> None:
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return json.dumps(self.payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def opener(request, timeout):
        requests.append((request, timeout))
        if "radar_runs" in request.full_url:
            return Response([{"run_key": "r1", "market_date": "2026-07-17"}])
        return Response([])

    history = fetch_dashboard_history(
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="private-key",
        opener=opener,
    )

    assert len(requests) == 6
    assert requests[0][0].get_header("X-radar-ingest-key") == "private-key"
    assert history["runs"][0]["run_key"] == "r1"


def test_write_dashboard_does_not_emit_credentials(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text("index", encoding="utf-8")
    assets = source / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("app", encoding="utf-8")
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps(_bundle(), ensure_ascii=False), encoding="utf-8")

    data_path = write_dashboard(bundle, tmp_path / "site", source)

    content = data_path.read_text(encoding="utf-8")
    assert "RADAR_INGEST_KEY" not in content
    assert "private-key" not in content
    assert (tmp_path / "site" / "index.html").exists()
    assert (tmp_path / "site" / "assets" / "app.js").exists()
