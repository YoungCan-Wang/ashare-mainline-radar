#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ashare_mainline_radar.ddl_gate import (
    DEFAULT_CONTRACT_PATH,
    live_schema_error,
    load_contract,
    missing_live_objects,
    parse_name_status,
    sql_diff_error,
)


def _changed_entries(base: str, head: str) -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "diff", "--name-status", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_name_status(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Block SQL commits and require live DDL before merge.",
    )
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT_PATH))
    parser.add_argument("--skip-live", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    if args.base:
        errors.append(sql_diff_error(_changed_entries(args.base, args.head)) or "")
        errors = [item for item in errors if item]

    if not args.skip_live:
        url = os.getenv("SUPABASE_URL")
        api_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")
        if not url or not api_key:
            errors.append(
                "SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY are required to verify live DDL."
            )
        else:
            contract = load_contract(Path(args.contract))
            errors.append(live_schema_error(missing_live_objects(url, api_key, contract)) or "")
            errors = [item for item in errors if item]

    if errors:
        print("\n\n".join(errors), file=sys.stderr)
        return 1
    print("DDL gate passed: no added or changed SQL, live schema matches the contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
