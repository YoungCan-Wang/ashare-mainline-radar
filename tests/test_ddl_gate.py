from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request

from ashare_mainline_radar.ddl_gate import (
    live_schema_error,
    load_contract,
    missing_live_objects,
    object_exists,
    parse_name_status,
    sql_diff_error,
    sql_paths,
)


class _Response:
    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return b"[]"


class _Router:
    def __init__(self, routes: dict[str, int | Exception]):
        self.routes = routes

    def opener(self, request: Request, timeout: float):
        status = self.routes[request.full_url]
        if isinstance(status, Exception):
            raise status
        if status >= 400:
            raise HTTPError(request.full_url, status, "error", hdrs=None, fp=None)
        return _Response(status)


def test_sql_paths_catch_migrations_and_ignore_code() -> None:
    assert sql_paths(
        [
            "ashare_mainline_radar/shadow_account.py",
            "supabase/migrations/20260813060000_apply_shadow_day.sql",
            "./docs/notes.md",
        ]
    ) == ["supabase/migrations/20260813060000_apply_shadow_day.sql"]


def test_sql_diff_error_blocks_commit() -> None:
    message = sql_diff_error(["supabase/migrations/new.sql", "README.md"])
    assert message is not None
    assert "Do not add or change .sql files" in message
    assert "supabase/migrations/new.sql" in message
    assert sql_diff_error(["ashare_mainline_radar/ddl_gate.py"]) is None


def test_sql_diff_allows_deleting_tracked_sql() -> None:
    assert sql_diff_error([("D", "supabase/migrations/old.sql")]) is None
    message = sql_diff_error([("M", "supabase/migrations/old.sql")])
    assert message is not None
    assert "M supabase/migrations/old.sql" in message


def test_parse_name_status_treats_rename_to_sql_as_add() -> None:
    rows = parse_name_status("R100\tdocs/old.sql\tsupabase/migrations/new.sql\nD\tkeep.sql\n")
    assert ("A", "supabase/migrations/new.sql") in rows
    assert ("D", "docs/old.sql") in rows
    assert ("D", "keep.sql") in rows
    assert sql_diff_error(rows) is not None


def test_load_contract_lists_shadow_rpc(tmp_path) -> None:
    path = tmp_path / "schema_contract.json"
    path.write_text(
        json.dumps({"tables": ["shadow_account"], "routines": ["apply_shadow_day"]}),
        encoding="utf-8",
    )
    contract = load_contract(path)
    assert contract["tables"] == ["shadow_account"]
    assert contract["routines"] == ["apply_shadow_day"]


def test_table_404_is_missing_other_client_errors_mean_exists() -> None:
    router = _Router(
        {
            "https://example.supabase.co/rest/v1/shadow_account?select=*&limit=0": 200,
            "https://example.supabase.co/rest/v1/missing_table?select=*&limit=0": 404,
            "https://example.supabase.co/rest/v1/private_table?select=*&limit=0": 401,
        }
    )
    assert object_exists("https://example.supabase.co", "key", "table", "shadow_account", router.opener)
    assert not object_exists("https://example.supabase.co", "key", "table", "missing_table", router.opener)
    assert object_exists("https://example.supabase.co", "key", "table", "private_table", router.opener)


def test_rpc_400_means_function_exists_404_means_missing() -> None:
    router = _Router(
        {
            "https://example.supabase.co/rest/v1/rpc/apply_shadow_day": 400,
            "https://example.supabase.co/rest/v1/rpc/missing_fn": 404,
        }
    )
    assert object_exists("https://example.supabase.co", "key", "routine", "apply_shadow_day", router.opener)
    assert not object_exists("https://example.supabase.co", "key", "routine", "missing_fn", router.opener)


def test_apply_shadow_day_probe_sends_named_arguments() -> None:
    seen: list[Request] = []

    def opener(request: Request, timeout: float):
        seen.append(request)
        raise HTTPError(request.full_url, 400, "radar ingest unauthorized", hdrs=None, fp=None)

    assert object_exists("https://example.supabase.co", "key", "routine", "apply_shadow_day", opener)
    assert json.loads(seen[0].data.decode("utf-8")) == {
        "p_account": {},
        "p_positions": [],
        "p_events": [],
        "p_nav": {},
    }


def test_repo_contract_loads() -> None:
    contract = load_contract()
    assert "shadow_account" in contract["tables"]
    assert "apply_shadow_day" in contract["routines"]


def test_live_schema_error_lists_missing_objects() -> None:
    router = _Router(
        {
            "https://example.supabase.co/rest/v1/shadow_account?select=*&limit=0": 200,
            "https://example.supabase.co/rest/v1/rpc/apply_shadow_day": 404,
        }
    )
    missing = missing_live_objects(
        "https://example.supabase.co",
        "key",
        {"tables": ["shadow_account"], "routines": ["apply_shadow_day"]},
        router.opener,
    )
    assert missing == ["routine:apply_shadow_day"]
    message = live_schema_error(missing)
    assert message is not None
    assert "Execute the local DDL" in message
    assert live_schema_error([]) is None
