#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ashare_mainline_radar.workflow_frequency import should_run_workflow


def _is_true(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _write_output(should_run: bool, reason: str) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(f"should_run={'true' if should_run else 'false'}\n")
            output.write(f"reason={reason}\n")
    print(f"should_run={'true' if should_run else 'false'}: {reason}")


def _fetch_runs(repository: str, workflow: str, branch: str, token: str) -> list[dict[str, object]]:
    query = urlencode({"branch": branch, "status": "completed", "per_page": 30})
    url = f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/runs?{query}"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ashare-mainline-radar",
        },
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return list(payload.get("workflow_runs") or [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Skip duplicate or overly frequent GitHub Actions runs.")
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--policy", choices=["daily", "backtest"], required=True)
    parser.add_argument("--min-hours", type=int, default=24)
    parser.add_argument("--force", default="false")
    args = parser.parse_args()

    if _is_true(args.force):
        _write_output(True, "force=true bypassed the frequency guard")
        return 0

    repository = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_REF_NAME")
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not repository or not branch or not token:
        _write_output(True, "GitHub runtime metadata is absent; frequency guard is inactive locally")
        return 0

    try:
        runs = _fetch_runs(repository, args.workflow, branch, token)
        should_run, reason = should_run_workflow(
            args.policy,
            runs,
            now=datetime.now(timezone.utc),
            current_run_id=os.getenv("GITHUB_RUN_ID"),
            head_sha=os.getenv("GITHUB_SHA"),
            min_hours=args.min_hours,
        )
    except Exception as exc:
        _write_output(False, f"frequency guard failed closed: {type(exc).__name__}: {exc}")
        return 0

    _write_output(should_run, reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
