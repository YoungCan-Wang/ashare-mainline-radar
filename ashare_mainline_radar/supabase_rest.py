from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


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
        with opener(request, timeout=30) as response:
            page = json.loads(response.read().decode("utf-8"))
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
) -> None:
    if not rows:
        return
    query = urlencode({"on_conflict": conflict_columns}, safe=",")
    headers = request_headers(api_key, ingest_key)
    headers.update(
        {
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
    )
    request = Request(
        f"{base_url.rstrip('/')}/rest/v1/{table}?{query}",
        data=json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with opener(request, timeout=30) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Supabase upsert to {table} returned HTTP {response.status}")
