from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen

from .quotes import ACTIONABLE_ROLES
from .supabase_rest import fetch_rows

DASHBOARD_SCHEMA_VERSION = "radar-dashboard-v2"


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
        return {"runs": [], "themes": [], "symbols": [], "selections": [], "quotes": [], "trade_plans": []}

    runs = fetch_rows(
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
    themes = fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_theme_snapshots",
        order="market_date.desc,rank.asc",
        max_rows=1000,
        filters=filters,
        opener=opener,
    )
    symbols = fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_symbol_snapshots",
        order="market_date.desc,priority_score.desc.nullslast",
        max_rows=5000,
        filters=filters,
        opener=opener,
    )
    selections = fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_symbol_selections",
        order="first_selected_at.asc",
        max_rows=10000,
        opener=opener,
    )
    quotes = fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_symbol_quotes",
        order="refreshed_at.desc",
        max_rows=10000,
        opener=opener,
    )
    trade_plans = fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_trade_plans",
        order="signal_date.desc,updated_at.desc",
        max_rows=10000,
        opener=opener,
    )
    return {
        "runs": runs,
        "themes": themes,
        "symbols": symbols,
        "selections": selections,
        "quotes": quotes,
        "trade_plans": trade_plans,
    }


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
    history = history or {"runs": [], "themes": [], "symbols": [], "selections": [], "quotes": [], "trade_plans": []}
    current_run = bundle.get("run") if isinstance(bundle.get("run"), dict) else {}
    local_runs = [current_run] if current_run else []
    local_themes = [row for row in bundle.get("themes", []) if isinstance(row, dict)]
    local_symbols = [row for row in bundle.get("symbols", []) if isinstance(row, dict)]

    runs = _merge_rows(history.get("runs", []), local_runs, ("run_key",))
    themes = _merge_rows(history.get("themes", []), local_themes, ("run_key", "theme"))
    symbols = _merge_rows(history.get("symbols", []), local_symbols, ("run_key", "symbol"))
    selections = {
        str(row.get("symbol")): row
        for row in history.get("selections", [])
        if isinstance(row, dict) and row.get("symbol")
    }
    quotes = {
        str(row.get("symbol")): row
        for row in history.get("quotes", [])
        if isinstance(row, dict) and row.get("symbol")
    }
    trade_plans: dict[str, dict[str, Any]] = {}
    for row in history.get("trade_plans", []):
        symbol = str(row.get("symbol") or "")
        if symbol and symbol not in trade_plans:
            trade_plans[symbol] = row
    enriched_symbols = []
    for row in symbols:
        enriched = dict(row)
        symbol = str(row.get("symbol") or "")
        selection = selections.get(symbol)
        roles = row.get("roles") if isinstance(row.get("roles"), list) else []
        if selection is None and ACTIONABLE_ROLES.intersection(str(role) for role in roles) and row.get("last_close"):
            selection = {
                "first_selected_at": row.get("updated_at"),
                "first_market_date": row.get("market_date"),
                "first_selected_price": row.get("last_close"),
            }
        quote = quotes.get(symbol)
        paper_plan = trade_plans.get(symbol) if row.get("run_key") == current_run.get("run_key") else None
        if selection:
            enriched.update(
                {
                    "first_selected_at": selection.get("first_selected_at"),
                    "first_market_date": selection.get("first_market_date"),
                    "first_selected_price": selection.get("first_selected_price"),
                }
            )
        if quote:
            enriched.update(
                {
                    "latest_price": quote.get("latest_price"),
                    "quote_at": quote.get("quote_at"),
                    "quote_date": quote.get("quote_date"),
                    "quote_refreshed_at": quote.get("refreshed_at"),
                    "daily_change_pct": quote.get("daily_change_pct"),
                }
            )
        else:
            enriched["latest_price"] = row.get("last_close")
        if paper_plan:
            enriched["paper_trade_plan"] = paper_plan
        selected_price = enriched.get("first_selected_price")
        latest_price = enriched.get("latest_price")
        if selected_price and latest_price:
            enriched["return_since_selection"] = float(latest_price) / float(selected_price) - 1
        enriched_symbols.append(enriched)
    symbols = enriched_symbols
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
        "current_run_key": current_run.get("run_key") or (runs[0].get("run_key") if runs else None),
        "quote_refreshed_at": max(
            (str(row.get("refreshed_at")) for row in quotes.values() if row.get("refreshed_at")),
            default=None,
        ),
        "runs": runs,
        "themes": themes,
        "symbols": symbols,
    }


def write_dashboard(
    bundle_path: str | Path | None,
    output_dir: str | Path,
    source_dir: str | Path,
    *,
    history: dict[str, list[dict[str, Any]]] | None = None,
) -> Path:
    bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8")) if bundle_path else {}
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
