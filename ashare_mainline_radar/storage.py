from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import RadarReport

SCHEMA_VERSION = "radar-storage-v1"
ROLE_ORDER = (
    "next_buy",
    "strong_stock",
    "golden_pit",
    "accumulation",
    "monthly_base",
    "expectation_gap",
    "leader_tape",
    "market_watchlist",
)


@dataclass(frozen=True)
class PersistenceStatus:
    status: str
    backend: str
    run_key: str
    theme_records: int
    symbol_records: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _payload(report: RadarReport | dict[str, Any]) -> dict[str, Any]:
    return report.to_dict() if isinstance(report, RadarReport) else report


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _run_key(report: dict[str, Any]) -> str:
    market_date = report.get("data_as_of") or str(report.get("generated_at") or "unknown")[:10]
    return f"cn:{market_date}:{report.get('mode') or 'unknown'}:{report.get('universe') or 'unknown'}"


def _candidate_sections(report: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    next_buy = _dict(report.get("next_buy"))
    next_candidates: list[dict[str, Any]] = []
    if isinstance(next_buy.get("primary"), dict):
        next_candidates.append(next_buy["primary"])
    next_candidates.extend(item for item in _list(next_buy.get("alternatives")) if isinstance(item, dict))
    for group in _list(next_buy.get("by_theme")):
        next_candidates.extend(item for item in _list(_dict(group).get("plans")) if isinstance(item, dict))

    return [
        ("next_buy", next_candidates),
        ("strong_stock", _list(_dict(report.get("strong_stocks")).get("candidates"))),
        ("golden_pit", _list(_dict(report.get("golden_pits")).get("candidates"))),
        ("accumulation", _list(_dict(report.get("accumulation")).get("candidates"))),
        ("monthly_base", _list(_dict(report.get("monthly_bases")).get("candidates"))),
        ("expectation_gap", _list(_dict(report.get("expectation_gaps")).get("signals"))),
        ("leader_tape", _list(report.get("leader_tape"))),
        ("market_watchlist", _list(report.get("market_watchlist"))),
    ]


def _themes(candidate: dict[str, Any]) -> list[str]:
    values = [str(value) for value in _list(candidate.get("themes")) if value]
    for key in ("theme", "primary_theme"):
        value = candidate.get(key)
        if value and value not in values:
            values.append(str(value))
    return values


def _first(candidate: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = candidate.get(key)
        if value is not None and value != "":
            return value
    return None


def _trade_plan(candidate: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "decision",
        "entry_plan",
        "confirmation",
        "invalidation",
        "position_note",
        "action",
        "lifecycle_stage",
        "independence_status",
    )
    return {key: candidate[key] for key in keys if candidate.get(key) not in (None, "")}


def _market_metrics(candidate: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "ret_1d",
        "ret_5d",
        "ret_20d",
        "range_position_60d",
        "drawdown_20d",
        "drawdown_60d",
        "drawdown_from_20d_high",
        "amount_ratio",
        "amount_ratio_1_5",
        "amount_ratio_5_20",
        "amount_ratio_10_30",
        "high_proximity_20d",
        "ma20_distance",
        "box_low",
        "box_high",
        "box_position",
    )
    return {key: candidate[key] for key in keys if candidate.get(key) is not None}


def build_storage_bundle(report: RadarReport | dict[str, Any]) -> dict[str, Any]:
    data = _payload(report)
    run_key = _run_key(data)
    market_date = data.get("data_as_of") or str(data.get("generated_at") or "")[:10]
    generated_at = data.get("generated_at")

    lifecycle_by_theme = {
        item.get("theme"): item
        for item in _list(_dict(data.get("theme_lifecycle")).get("signals"))
        if isinstance(item, dict) and item.get("theme")
    }
    themes = []
    for rank, theme in enumerate(_list(data.get("themes")), start=1):
        if not isinstance(theme, dict) or not theme.get("name"):
            continue
        name = str(theme["name"])
        themes.append(
            {
                "run_key": run_key,
                "market_date": market_date,
                "theme": name,
                "rank": rank,
                "status": theme.get("status"),
                "score": theme.get("score"),
                "lifecycle_stage": _dict(lifecycle_by_theme.get(name)).get("stage"),
                "snapshot": theme,
                "lifecycle": lifecycle_by_theme.get(name) or {},
                "updated_at": generated_at,
            }
        )

    fundamentals = {
        item.get("symbol"): item
        for item in _list(_dict(data.get("fundamentals")).get("snapshots"))
        if isinstance(item, dict) and item.get("symbol")
    }
    targets = {
        item.get("symbol"): item
        for item in _list(_dict(data.get("target_prices")).get("estimates"))
        if isinstance(item, dict) and item.get("symbol")
    }
    symbols: dict[str, dict[str, Any]] = {}
    for role, candidates in _candidate_sections(data):
        for candidate in candidates:
            if not isinstance(candidate, dict) or not candidate.get("symbol"):
                continue
            symbol = str(candidate["symbol"])
            row = symbols.setdefault(
                symbol,
                {
                    "run_key": run_key,
                    "market_date": market_date,
                    "symbol": symbol,
                    "exchange": symbol.rsplit(".", 1)[-1] if "." in symbol else None,
                    "name": candidate.get("name") or symbol,
                    "primary_theme": None,
                    "themes": [],
                    "roles": [],
                    "action_state": None,
                    "priority_score": None,
                    "last_close": None,
                    "market_metrics": {},
                    "signal_payload": {},
                    "fundamental_payload": {},
                    "target_payload": {},
                    "trade_plan": {},
                    "updated_at": generated_at,
                },
            )
            if role not in row["roles"]:
                row["roles"].append(role)
            row["signal_payload"][role] = candidate
            for theme in _themes(candidate):
                if theme not in row["themes"]:
                    row["themes"].append(theme)
            row["primary_theme"] = row["primary_theme"] or _first(candidate, ("theme", "primary_theme"))
            row["action_state"] = row["action_state"] or _first(
                candidate, ("decision", "action", "status", "stage")
            )
            candidate_score = _first(candidate, ("priority_score", "score"))
            if candidate_score is not None:
                current_score = row["priority_score"]
                row["priority_score"] = max(float(candidate_score), float(current_score or candidate_score))
            row["last_close"] = row["last_close"] or candidate.get("last_close")
            row["market_metrics"].update(_market_metrics(candidate))
            row["trade_plan"].update(_trade_plan(candidate))

    for symbol, row in symbols.items():
        row["roles"] = sorted(row["roles"], key=ROLE_ORDER.index)
        row["fundamental_payload"] = fundamentals.get(symbol) or {}
        row["target_payload"] = targets.get(symbol) or {}

    gate = _dict(data.get("trading_gate"))
    run = {
        "run_key": run_key,
        "market_date": market_date,
        "generated_at": generated_at,
        "mode": data.get("mode"),
        "universe": data.get("universe"),
        "scanned_symbols": data.get("scanned_symbols") or 0,
        "top_theme": _dict(_list(data.get("themes"))[0] if _list(data.get("themes")) else {}).get("name"),
        "gate_level": gate.get("level"),
        "gate_state": gate.get("state"),
        "gate_score": gate.get("score"),
        "summary": {
            "market_structure": data.get("market_structure") or {},
            "warnings": data.get("warnings") or [],
            "cross_market": data.get("cross_market") or {},
            "source_statuses": data.get("source_statuses") or [],
        },
        "updated_at": generated_at,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "run": run,
        "themes": themes,
        "symbols": list(symbols.values()),
    }


def _upsert(
    base_url: str,
    api_key: str,
    ingest_key: str | None,
    table: str,
    conflict_columns: str,
    rows: list[dict[str, Any]],
    opener: Callable[..., Any],
) -> None:
    if not rows:
        return
    query = urlencode({"on_conflict": conflict_columns}, safe=",")
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
        "User-Agent": "ashare-mainline-radar",
    }
    if api_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {api_key}"
    if ingest_key:
        headers["x-radar-ingest-key"] = ingest_key
    request = Request(
        f"{base_url.rstrip('/')}/rest/v1/{table}?{query}",
        data=json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with opener(request, timeout=30) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Supabase upsert to {table} returned HTTP {response.status}")


def persist_report(
    report: RadarReport | dict[str, Any],
    output_dir: str | Path,
    *,
    backend: str = "auto",
    supabase_url: str | None = None,
    supabase_secret_key: str | None = None,
    supabase_publishable_key: str | None = None,
    radar_ingest_key: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> PersistenceStatus:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    bundle = build_storage_bundle(report)
    bundle_path = output / "storage_bundle.json"
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    url = supabase_url or os.getenv("SUPABASE_URL")
    secret_key = (
        supabase_secret_key
        or os.getenv("SUPABASE_SECRET_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )
    publishable_key = supabase_publishable_key or os.getenv("SUPABASE_PUBLISHABLE_KEY")
    ingest_key = radar_ingest_key or os.getenv("RADAR_INGEST_KEY")
    api_key = secret_key or publishable_key
    credentials_ready = bool(secret_key or (publishable_key and ingest_key))
    resolved_backend = backend
    if backend == "auto":
        resolved_backend = "supabase" if url and credentials_ready else "artifact"

    run_key = str(bundle["run"]["run_key"])
    if resolved_backend == "none":
        status = PersistenceStatus(
            "skipped", "none", run_key, len(bundle["themes"]), len(bundle["symbols"]), "persistence disabled"
        )
    elif resolved_backend == "artifact":
        status = PersistenceStatus(
            "deferred",
            "artifact",
            run_key,
            len(bundle["themes"]),
            len(bundle["symbols"]),
            "Supabase credentials are absent; normalized bundle kept in the workflow artifact",
        )
    elif resolved_backend == "supabase" and (not url or not api_key or not credentials_ready):
        status = PersistenceStatus(
            "failed",
            "supabase",
            run_key,
            len(bundle["themes"]),
            len(bundle["symbols"]),
            "configure SUPABASE_URL plus either a server secret key or SUPABASE_PUBLISHABLE_KEY with RADAR_INGEST_KEY",
        )
    elif resolved_backend == "supabase":
        try:
            _upsert(str(url), str(api_key), ingest_key, "radar_runs", "run_key", [bundle["run"]], opener)
            _upsert(
                str(url),
                str(api_key),
                ingest_key,
                "radar_theme_snapshots",
                "run_key,theme",
                bundle["themes"],
                opener,
            )
            _upsert(
                str(url),
                str(api_key),
                ingest_key,
                "radar_symbol_snapshots",
                "run_key,symbol",
                bundle["symbols"],
                opener,
            )
            status = PersistenceStatus(
                "stored",
                "supabase",
                run_key,
                len(bundle["themes"]),
                len(bundle["symbols"]),
                "normalized snapshots upserted",
            )
        except Exception as exc:
            status = PersistenceStatus(
                "failed",
                "supabase",
                run_key,
                len(bundle["themes"]),
                len(bundle["symbols"]),
                f"{type(exc).__name__}: {exc}",
            )
    else:
        raise ValueError(f"Unknown storage backend: {backend}")

    (output / "storage_status.json").write_text(
        json.dumps(status.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return status
