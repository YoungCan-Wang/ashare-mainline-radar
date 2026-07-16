from __future__ import annotations

import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from typing import Any, TypeVar

from .models import KlineSeries

FREE_BASE_URL = "https://free-api.tickflow.org"
FULL_BASE_URL = "https://api.tickflow.org"
DEFAULT_MIN_INTERVAL = 2.05


class TickFlowError(RuntimeError):
    pass


T = TypeVar("T")


def chunked(items: Iterable[T], size: int) -> Iterable[list[T]]:
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


class TickFlowClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 20.0,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        retries: int = 3,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("TICKFLOW_API_KEY")
        self.base_url = (base_url or os.getenv("TICKFLOW_BASE_URL") or (FULL_BASE_URL if self.api_key else FREE_BASE_URL)).rstrip("/")
        self.timeout = timeout
        self.min_interval = min_interval
        self.retries = max(1, retries)
        self._last_request_at = 0.0

    @property
    def source_label(self) -> str:
        return f"TickFlow {'full' if self.api_key else 'free'} API ({self.base_url})"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
        self._throttle()
        query = urllib.parse.urlencode(params or {}, doseq=True)
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "ashare-mainline-radar/0.1",
        }
        data = None
        if self.api_key:
            headers["x-api-key"] = self.api_key
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
        last_error: BaseException | None = None
        for attempt in range(1, self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self._last_request_at = time.monotonic()
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                message = exc.read().decode("utf-8", errors="replace")
                if exc.code == 429:
                    last_error = exc
                    retry_after = exc.headers.get("Retry-After")
                    try:
                        wait_seconds = float(retry_after) if retry_after else 2.1 * attempt
                    except ValueError:
                        wait_seconds = 2.1 * attempt
                    if attempt < self.retries:
                        time.sleep(max(2.1, wait_seconds))
                        continue
                if 400 <= exc.code < 500:
                    raise TickFlowError(f"TickFlow HTTP {exc.code} for {path}: {message}") from exc
                last_error = exc
            except (urllib.error.URLError, http.client.HTTPException, TimeoutError, socket.timeout) as exc:
                last_error = exc
            if attempt < self.retries:
                time.sleep(0.4 * attempt)
        raise TickFlowError(f"TickFlow request failed for {path}: {last_error}") from last_error

    def get_universe(self, universe_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/v1/universes/{urllib.parse.quote(universe_id)}")
        return dict(payload.get("data") or {})

    def get_instruments(self, symbols: list[str], chunk_size: int = 1000) -> dict[str, dict[str, Any]]:
        instruments: dict[str, dict[str, Any]] = {}
        for batch in chunked(symbols, chunk_size):
            payload = self._request("POST", "/v1/instruments", body={"symbols": batch})
            data = payload.get("data") or []
            for item in data:
                symbol = str(item.get("symbol"))
                instruments[symbol] = dict(item)
        return instruments

    def get_klines_batch(
        self,
        symbols: list[str],
        period: str = "1d",
        count: int = 80,
        adjust: str = "forward",
        chunk_size: int = 80,
    ) -> dict[str, KlineSeries]:
        series: dict[str, KlineSeries] = {}
        for batch in chunked(symbols, chunk_size):
            payload = self._request(
                "GET",
                "/v1/klines/batch",
                params={
                    "symbols": ",".join(batch),
                    "period": period,
                    "count": count,
                    "adjust": adjust,
                },
            )
            for symbol, compact in (payload.get("data") or {}).items():
                parsed = KlineSeries.from_compact(symbol, compact)
                if parsed.usable:
                    series[symbol] = parsed
        return series

    def get_financial_metrics(self, symbols: list[str], chunk_size: int = 80) -> dict[str, list[dict[str, Any]]]:
        metrics: dict[str, list[dict[str, Any]]] = {}
        for batch in chunked(symbols, chunk_size):
            payload = self._request(
                "GET",
                "/v1/financials/metrics",
                params={"symbols": ",".join(batch)},
            )
            for symbol, records in (payload.get("data") or {}).items():
                metrics[str(symbol)] = [dict(record) for record in (records or [])]
        return metrics
