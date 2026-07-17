from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
MARKET_CLOSE = time(15, 0)


def parse_github_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def should_run_workflow(
    policy: str,
    runs: list[dict[str, Any]],
    *,
    now: datetime,
    current_run_id: str | None = None,
    head_sha: str | None = None,
    min_hours: int = 24,
) -> tuple[bool, str]:
    successful = [
        run
        for run in runs
        if str(run.get("id")) != str(current_run_id)
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    ]

    if policy == "daily":
        market_now = now.astimezone(CN_TIMEZONE)
        market_date = market_now.date()
        after_close = market_now.time() >= MARKET_CLOSE
        for run in successful:
            created_at = run.get("created_at")
            if not created_at:
                continue
            run_time = parse_github_timestamp(str(created_at)).astimezone(CN_TIMEZONE)
            same_session = (run_time.time() >= MARKET_CLOSE) == after_close
            if run_time.date() == market_date and same_session:
                session = "post-close" if after_close else "pre-close"
                return False, f"a successful {session} daily run already exists for {market_date.isoformat()}"
        session = "post-close" if after_close else "pre-close"
        return True, f"no successful {session} daily run exists for {market_date.isoformat()}"

    if policy == "backtest":
        cutoff = now.astimezone(timezone.utc) - timedelta(hours=min_hours)
        for run in successful:
            created_at = run.get("created_at")
            if not created_at or (head_sha and run.get("head_sha") != head_sha):
                continue
            if parse_github_timestamp(str(created_at)) >= cutoff:
                return False, f"the same commit already completed a backtest within {min_hours} hours"
        return True, f"no successful backtest for this commit exists within {min_hours} hours"

    raise ValueError(f"Unknown frequency policy: {policy}")
