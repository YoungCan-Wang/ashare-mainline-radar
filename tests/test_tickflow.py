import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from ashare_mainline_radar.tickflow import DEFAULT_MIN_INTERVAL, TickFlowClient, TickFlowError


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_tickflow_retries_rate_limit_response() -> None:
    error = urllib.error.HTTPError(
        url="https://api.tickflow.org/v1/universes/CN_Equity_A",
        code=429,
        msg="Too Many Requests",
        hdrs={"Retry-After": "0.5"},
        fp=io.BytesIO(b'{"code":"RATE_LIMITED"}'),
    )
    client = TickFlowClient(api_key="test", min_interval=0, retries=2)
    with patch("urllib.request.urlopen", side_effect=[error, _Response({"data": {"symbols": []}})]), patch(
        "time.sleep"
    ) as sleep:
        universe = client.get_universe("CN_Equity_A")
    assert universe == {"symbols": []}
    sleep.assert_called_once_with(2.1)


def test_instruments_use_large_post_batches() -> None:
    client = TickFlowClient(api_key="test", min_interval=0)
    with patch.object(client, "_request", return_value={"data": []}) as request:
        client.get_instruments([f"{idx:06d}.SZ" for idx in range(1001)])
    assert request.call_count == 2
    assert request.call_args_list[0].args[:2] == ("POST", "/v1/instruments")


def test_default_throttle_stays_below_provider_rate_limit() -> None:
    client = TickFlowClient(api_key="test")

    assert DEFAULT_MIN_INTERVAL >= 60 / 30
    assert client.min_interval == DEFAULT_MIN_INTERVAL


def test_realtime_quotes_are_parsed_by_symbol() -> None:
    client = TickFlowClient(api_key="test", min_interval=0)
    payload = {
        "data": [
            {
                "symbol": "300122.SZ",
                "last_price": 36.5,
                "prev_close": 35.0,
                "timestamp": 1784255400000,
                "session": "regular",
                "ext": {"name": "智飞生物", "change_pct": 0.042857},
            }
        ]
    }
    with patch.object(client, "_request", return_value=payload) as request:
        quotes = client.get_quotes(["300122.SZ"])

    assert quotes["300122.SZ"].last_price == 36.5
    assert quotes["300122.SZ"].change_pct == 0.042857
    assert request.call_args.kwargs["params"] == {"symbols": "300122.SZ"}


def test_realtime_quotes_require_api_key() -> None:
    client = TickFlowClient(api_key="", base_url="https://free-api.tickflow.org")

    with pytest.raises(TickFlowError, match="required"):
        client.get_quotes(["300122.SZ"])
