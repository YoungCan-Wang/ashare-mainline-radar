import json
from datetime import datetime, timezone

from ashare_mainline_radar.quotes import refresh_selected_quotes
from ashare_mainline_radar.tickflow import QuoteSnapshot


class _Response:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status = status

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _Client:
    def get_quotes(self, symbols):
        assert symbols == ["300122.SZ"]
        return {
            "300122.SZ": QuoteSnapshot(
                symbol="300122.SZ",
                last_price=38.5,
                prev_close=37.0,
                change_pct=None,
                timestamp=1784255400000,
                session="regular",
                name="智飞生物",
            )
        }


def test_refresh_quotes_only_fetches_current_actionable_pool() -> None:
    requests = []

    def opener(request, timeout):
        requests.append(request)
        if request.get_method() == "POST":
            return _Response(status=201)
        if "radar_runs" in request.full_url:
            return _Response([{"run_key": "cn:2026-07-17:universe:CN_Equity_A"}])
        return _Response(
            [
                {"symbol": "300122.SZ", "roles": ["next_buy"]},
                {"symbol": "600000.SH", "roles": ["market_watchlist"]},
            ]
        )

    status = refresh_selected_quotes(
        client=_Client(),
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="private-key",
        now=datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc),
        opener=opener,
    )

    assert status.status == "refreshed"
    assert status.requested_symbols == 1
    assert status.refreshed_symbols == 1
    payload = json.loads(requests[-1].data)
    assert payload[0]["symbol"] == "300122.SZ"
    assert payload[0]["daily_change_pct"] == 38.5 / 37.0 - 1
