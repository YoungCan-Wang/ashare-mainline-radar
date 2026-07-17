from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DASHBOARD_SCHEMA_VERSION = "radar-dashboard-v1"


def _request_headers(api_key: str, ingest_key: str) -> dict[str, str]:
    headers = {
        "apikey": api_key,
        "x-radar-ingest-key": ingest_key,
        "Accept": "application/json",
        "User-Agent": "ashare-mainline-radar",
    }
    if api_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _fetch_rows(
    base_url: str,
    api_key: str,
    ingest_key: str,
    table: str,
    *,
    order: str,
    max_rows: int,
    filters: dict[str, str] | None = None,
    opener: Callable[..., Any] = urlopen,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while offset < max_rows:
        limit = min(page_size, max_rows - offset)
        query = {"select": "*", "order": order, "offset": str(offset), "limit": str(limit)}
        query.update(filters or {})
        request = Request(
            f"{base_url.rstrip('/')}/rest/v1/{table}?{urlencode(query, safe=',.*()')}",
            headers=_request_headers(api_key, ingest_key),
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


def fetch_dashboard_history(
    *,
    supabase_url: str | None = None,
    supabase_publishable_key: str | None = None,
    radar_ingest_key: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, list[dict[str, Any]]]:
    url = supabase_url or os.getenv("SUPABASE_URL")
    api_key = supabase_publishable_key or os.getenv("SUPABASE_PUBLISHABLE_KEY")
    ingest_key = radar_ingest_key or os.getenv("RADAR_INGEST_KEY")
    if not url or not api_key or not ingest_key:
        return {"runs": [], "themes": [], "symbols": []}

    runs = _fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_runs",
        order="market_date.desc,generated_at.desc",
        max_rows=60,
        opener=opener,
    )
    earliest_date = min((str(run.get("market_date")) for run in runs if run.get("market_date")), default=None)
    filters = {"market_date": f"gte.{earliest_date}"} if earliest_date else None
    themes = _fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_theme_snapshots",
        order="market_date.desc,rank.asc",
        max_rows=1000,
        filters=filters,
        opener=opener,
    )
    symbols = _fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_symbol_snapshots",
        order="market_date.desc,priority_score.desc.nullslast",
        max_rows=5000,
        filters=filters,
        opener=opener,
    )
    return {"runs": runs, "themes": themes, "symbols": symbols}


def _merge_rows(
    remote: list[dict[str, Any]], local: list[dict[str, Any]], key_fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in [*remote, *local]:
        key = tuple(row.get(field) for field in key_fields)
        if all(value is not None for value in key):
            merged[key] = row
    return list(merged.values())


def build_dashboard_payload(
    bundle: dict[str, Any], history: dict[str, list[dict[str, Any]]] | None = None
) -> dict[str, Any]:
    history = history or {"runs": [], "themes": [], "symbols": []}
    current_run = bundle.get("run") if isinstance(bundle.get("run"), dict) else {}
    local_runs = [current_run] if current_run else []
    local_themes = [row for row in bundle.get("themes", []) if isinstance(row, dict)]
    local_symbols = [row for row in bundle.get("symbols", []) if isinstance(row, dict)]

    runs = _merge_rows(history.get("runs", []), local_runs, ("run_key",))
    themes = _merge_rows(history.get("themes", []), local_themes, ("run_key", "theme"))
    symbols = _merge_rows(history.get("symbols", []), local_symbols, ("run_key", "symbol"))
    runs.sort(key=lambda row: (str(row.get("market_date") or ""), str(row.get("generated_at") or "")), reverse=True)
    run_order = {str(row.get("run_key")): index for index, row in enumerate(runs)}
    themes.sort(key=lambda row: (run_order.get(str(row.get("run_key")), 9999), int(row.get("rank") or 9999)))
    symbols.sort(
        key=lambda row: (
            run_order.get(str(row.get("run_key")), 9999),
            -float(row.get("priority_score") or 0),
            str(row.get("symbol") or ""),
        )
    )
    return {
        "schema_version": DASHBOARD_SCHEMA_VERSION,
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "current_run_key": current_run.get("run_key"),
        "runs": runs,
        "themes": themes,
        "symbols": symbols,
    }


def write_dashboard(
    bundle_path: str | Path,
    output_dir: str | Path,
    source_dir: str | Path,
    *,
    history: dict[str, list[dict[str, Any]]] | None = None,
) -> Path:
    bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    payload = build_dashboard_payload(bundle, history)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source = Path(source_dir)
    if not (source / "index.html").exists():
        raise FileNotFoundError(f"Dashboard build is missing: {source / 'index.html'}")
    for item in source.iterdir():
        destination = output / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(item, destination)
    data_path = output / "data.json"
    data_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return data_path
