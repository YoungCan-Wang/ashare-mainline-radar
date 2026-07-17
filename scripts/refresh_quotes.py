#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ashare_mainline_radar.quotes import refresh_selected_quotes


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh TickFlow quotes for the current actionable radar pool.")
    parser.add_argument("--output", type=Path, default=Path("reports/quotes/quote_refresh.json"))
    parser.add_argument("--allow-stale", action="store_true", help="Accept the provider's latest non-current quote date.")
    args = parser.parse_args()

    status = refresh_selected_quotes(require_current_market_date=not args.allow_stale)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(status.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as output:
            output.write(f"should_deploy={'true' if status.should_deploy else 'false'}\n")
            output.write(f"refresh_status={status.status}\n")
    print(
        f"Quote refresh: {status.status}; requested={status.requested_symbols} "
        f"refreshed={status.refreshed_symbols}; {status.message}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
