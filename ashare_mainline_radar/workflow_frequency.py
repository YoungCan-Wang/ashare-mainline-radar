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


def daily_session(now: datetime, *, last_bar_date: date | None = None) -> tuple[date, bool]:
    """Return (session_date, after_close) in Asia/Shanghai.

    A session's post-close window is T 15:00 through the next A-share open
    (09:30 on the next trading day). Overnight, weekends, and holidays stay
    on T. Calendar midnight does not start a new Daily identity.
    """
    market_now = now.astimezone(CN_TIMEZONE)
    market_date = market_now.date()
    after_open = market_now.time() >= MARKET_OPEN
    after_close = market_now.time() >= MARKET_CLOSE

    if last_bar_date is not None:
        if market_date == last_bar_date:
            return last_bar_date, after_close
        if market_date.weekday() >= 5 or not after_open:
            return last_bar_date, True
        if after_close and last_bar_date < market_date:
            return last_bar_date, True
        return market_date, after_close

    if after_close:
        if market_date.weekday() < 5:
            return market_date, True
        return previous_weekday(market_date), True
    if market_date.weekday() >= 5 or not after_open:
        return previous_weekday(market_date), True
    return market_date, False


def session_as_of(now: datetime, *, last_bar_date: date | None = None) -> date:
    return daily_session(now, last_bar_date=last_bar_date)[0]


def should_run_workflow(
    policy: str,
    runs: list[dict[str, Any]],
    *,
    now: datetime,
    current_run_id: str | None = None,
    head_sha: str | None = None,
    min_hours: int = 24,
    event_name: str | None = None,
    last_bar_date: date | None = None,
) -> tuple[bool, str]:
    _ = event_name
    successful = [
        run
        for run in runs
        if str(run.get("id")) != str(current_run_id)
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    ]

    if policy == "daily":
        session_date, after_close = daily_session(now, last_bar_date=last_bar_date)
        for run in successful:
            created_at = run.get("created_at")
            if not created_at:
                continue
            run_time = parse_github_timestamp(str(created_at))
            run_date, run_after_close = daily_session(run_time, last_bar_date=last_bar_date)
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
