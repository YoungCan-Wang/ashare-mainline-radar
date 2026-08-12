from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_UPSERT_BATCH_SIZE = 100


def request_headers(api_key: str, ingest_key: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": api_key,
        "Accept": "application/json",
        "User-Agent": "ashare-mainline-radar",
    }
    if api_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {api_key}"
    if ingest_key:
        headers["x-radar-ingest-key"] = ingest_key
    return headers


def _read_http_error_body(exc: HTTPError, *, limit: int = 2000) -> str:
    try:
        raw = exc.read()
    except Exception:
        return ""
    if not raw:
        return ""
    text = raw.decode("utf-8", errors="replace").strip()
    if len(text) > limit:
        return f"{text[:limit]}…"
    return text


def format_http_error(exc: HTTPError, *, context: str) -> str:
    body = _read_http_error_body(exc)
    suffix = f"; body={body}" if body else ""
    return f"{context}: HTTP {exc.code} {exc.reason}{suffix}"


def fetch_rows(
    base_url: str,
    api_key: str,
    ingest_key: str | None,
    table: str,
    *,
    order: str | None,
    max_rows: int,
    filters: dict[str, str] | None = None,
    opener: Callable[..., Any] = urlopen,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while offset < max_rows:
        limit = min(page_size, max_rows - offset)
        query = {"select": "*", "offset": str(offset), "limit": str(limit)}
        if order:
            query["order"] = order
        query.update(filters or {})
        request = Request(
            f"{base_url.rstrip('/')}/rest/v1/{table}?{urlencode(query, safe=',.*(){}')}",
            headers=request_headers(api_key, ingest_key),
        )
        try:
            with opener(request, timeout=30) as response:
                page = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(format_http_error(exc, context=f"Supabase query for {table} failed")) from exc
        if not isinstance(page, list):
            raise RuntimeError(f"Supabase query for {table} did not return a list")
        rows.extend(item for item in page if isinstance(item, dict))
        if len(page) < limit:
            break
        offset += limit
    return rows


def upsert_rows(
    base_url: str,
    api_key: str,
    ingest_key: str | None,
    table: str,
    conflict_columns: str,
    rows: list[dict[str, Any]],
    opener: Callable[..., Any] = urlopen,
    *,
    batch_size: int = DEFAULT_UPSERT_BATCH_SIZE,
) -> None:
    if not rows:
        return
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    query = urlencode({"on_conflict": conflict_columns}, safe=",")
    headers = request_headers(api_key, ingest_key)
    headers.update(
        {
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
    )
    endpoint = f"{base_url.rstrip('/')}/rest/v1/{table}?{query}"
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        request = Request(
            endpoint,
            data=json.dumps(chunk, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with opener(request, timeout=30) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"Supabase upsert to {table} returned HTTP {response.status}")
        except HTTPError as exc:
            raise RuntimeError(format_http_error(exc, context=f"Supabase upsert to {table} failed")) from exc
