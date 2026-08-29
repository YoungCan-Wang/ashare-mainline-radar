from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(15, 0)


def parse_github_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def previous_weekday(day: date) -> date:
    previous = day - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous


def daily_session(now: datetime, *, scheduled: bool = False) -> tuple[date, bool]:
    """Return (session_date, after_close) in Asia/Shanghai.

    A weekday post-close Daily that slips past midnight is still that
    session's post-close slot, not the next calendar day's pre-close.
    """
    market_now = now.astimezone(CN_TIMEZONE)
    market_date = market_now.date()
    if market_now.time() >= MARKET_CLOSE:
        return market_date, True
    overnight_delay = scheduled or market_date.weekday() >= 5 or market_now.time() < MARKET_OPEN
    if overnight_delay:
        return previous_weekday(market_date), True
    return market_date, False


def should_run_workflow(
    policy: str,
    runs: list[dict[str, Any]],
    *,
    now: datetime,
    current_run_id: str | None = None,
    head_sha: str | None = None,
    min_hours: int = 24,
    event_name: str | None = None,
) -> tuple[bool, str]:
    successful = [
        run
        for run in runs
        if str(run.get("id")) != str(current_run_id)
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    ]

    if policy == "daily":
        scheduled = (event_name or "") == "schedule"
        session_date, after_close = daily_session(now, scheduled=scheduled)
        for run in successful:
            created_at = run.get("created_at")
            if not created_at:
                continue
            run_time = parse_github_timestamp(str(created_at))
            run_scheduled = str(run.get("event") or "") == "schedule"
            run_date, run_after_close = daily_session(run_time, scheduled=run_scheduled)
            if run_date == session_date and run_after_close == after_close:
                session = "post-close" if after_close else "pre-close"
                return False, f"a successful {session} daily run already exists for {session_date.isoformat()}"
        session = "post-close" if after_close else "pre-close"
        return True, f"no successful {session} daily run exists for {session_date.isoformat()}"

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
