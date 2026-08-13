from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .supabase_rest import format_http_error, request_headers

DEFAULT_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "supabase" / "schema_contract.json"
RPC_PROBE_PAYLOADS = {
    "apply_shadow_day": {
        "p_account": {},
        "p_positions": [],
        "p_events": [],
        "p_nav": {},
    }
}


def sql_paths(paths: list[str]) -> list[str]:
    found: list[str] = []
    for raw in paths:
        path = raw.replace("\\", "/").lstrip("./")
        if path.endswith(".sql"):
            found.append(path)
    return found


def load_contract(path: Path | None = None) -> dict[str, list[str]]:
    contract_path = path or DEFAULT_CONTRACT_PATH
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    tables = [str(item) for item in payload.get("tables") or [] if str(item).strip()]
    routines = [str(item) for item in payload.get("routines") or [] if str(item).strip()]
    if not tables and not routines:
        raise ValueError(f"{contract_path} must list tables or routines")
    return {"tables": tables, "routines": routines}


def _status_or_error(exc: BaseException) -> int | None:
    if isinstance(exc, HTTPError):
        return int(exc.code)
    return None


def object_exists(
    url: str,
    api_key: str,
    kind: str,
    name: str,
    opener: Callable[..., Any] = urlopen,
) -> bool:
    headers = request_headers(api_key)
    if kind == "table":
        request = Request(
            f"{url.rstrip('/')}/rest/v1/{name}?select=*&limit=0",
            headers=headers,
            method="GET",
        )
    elif kind == "routine":
        headers = {**headers, "Content-Type": "application/json"}
        payload = RPC_PROBE_PAYLOADS.get(name, {})
        request = Request(
            f"{url.rstrip('/')}/rest/v1/rpc/{name}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
    else:
        raise ValueError(f"unsupported schema object kind: {kind}")
    try:
        with opener(request, timeout=20) as response:
            return 200 <= int(response.status) < 500 and int(response.status) != 404
    except HTTPError as exc:
        if exc.code == 404:
            return False
        if 400 <= exc.code < 500:
            return True
        raise RuntimeError(format_http_error(exc, context=f"Supabase {kind} {name} probe failed")) from exc


def missing_live_objects(
    url: str,
    api_key: str,
    contract: dict[str, list[str]],
    opener: Callable[..., Any] = urlopen,
) -> list[str]:
    missing: list[str] = []
    for table in contract["tables"]:
        if not object_exists(url, api_key, "table", table, opener):
            missing.append(f"table:{table}")
    for routine in contract["routines"]:
        if not object_exists(url, api_key, "routine", routine, opener):
            missing.append(f"routine:{routine}")
    return missing


def sql_diff_error(paths: list[str]) -> str | None:
    found = sql_paths(paths)
    if not found:
        return None
    listed = "\n".join(f"- {path}" for path in found)
    return (
        "Do not commit .sql files. Apply DDL on live Supabase first, then merge application code only.\n"
        f"{listed}"
    )


def live_schema_error(missing: list[str]) -> str | None:
    if not missing:
        return None
    listed = "\n".join(f"- {item}" for item in missing)
    return (
        "Live Supabase is missing contracted schema objects. Execute the local DDL, then re-run this check.\n"
        f"{listed}"
    )
