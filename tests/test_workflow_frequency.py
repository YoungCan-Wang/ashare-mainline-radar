from datetime import date, datetime, timezone

from ashare_mainline_radar.workflow_frequency import daily_session, should_run_workflow

NOW = datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc)


def _run(
    run_id: int,
    created_at: str,
    *,
    head_sha: str = "abc",
    conclusion: str = "success",
    event: str | None = None,
) -> dict:
    payload = {
        "id": run_id,
        "status": "completed",
        "conclusion": conclusion,
        "created_at": created_at,
        "head_sha": head_sha,
    }
    if event is not None:
        payload["event"] = event
    return payload


def test_daily_policy_skips_second_success_on_same_beijing_date() -> None:
    should_run, reason = should_run_workflow(
        "daily",
        [_run(1, "2026-07-17T08:50:00Z")],
        now=NOW,
        current_run_id="2",
    )

    assert should_run is False
    assert "2026-07-17" in reason


def test_daily_policy_allows_retry_after_failure() -> None:
    should_run, _ = should_run_workflow(
        "daily",
        [_run(1, "2026-07-17T08:50:00Z", conclusion="failure")],
        now=NOW,
    )

    assert should_run is True


def test_daily_policy_does_not_let_morning_manual_run_block_close_report() -> None:
    should_run, reason = should_run_workflow(
        "daily",
        [_run(1, "2026-07-17T02:00:00Z")],
        now=NOW,
    )

    assert should_run is True
    assert "post-close" in reason


def test_daily_policy_treats_overnight_delay_as_weekday_post_close() -> None:
    # Saturday 04:22 Beijing = Friday 20:22 UTC; still Friday's post-close window.
    now = datetime(2026, 8, 28, 20, 22, tzinfo=timezone.utc)
    should_run, reason = should_run_workflow("daily", [], now=now)

    assert should_run is True
    assert "post-close" in reason
    assert "2026-08-28" in reason


def test_daily_policy_skips_overnight_delay_when_weekday_post_close_exists() -> None:
    now = datetime(2026, 8, 28, 20, 22, tzinfo=timezone.utc)
    should_run, reason = should_run_workflow(
        "daily",
        [_run(1, "2026-08-28T08:50:00Z")],
        now=now,
    )

    assert should_run is False
    assert "post-close" in reason
    assert "2026-08-28" in reason


def test_daily_policy_keeps_weekday_morning_dispatch_as_pre_close() -> None:
    now = datetime(2026, 8, 28, 2, 0, tzinfo=timezone.utc)
    should_run, reason = should_run_workflow(
        "daily",
        [_run(1, "2026-08-27T08:50:00Z")],
        now=now,
    )

    assert should_run is True
    assert "pre-close" in reason
    assert "2026-08-28" in reason


def test_session_window_uses_last_bar_across_weekend() -> None:
    now = datetime(2026, 8, 28, 20, 22, tzinfo=timezone.utc)
    session_date, after_close = daily_session(now, last_bar_date=date(2026, 8, 28))

    assert session_date == date(2026, 8, 28)
    assert after_close is True


def test_session_window_keeps_holiday_friday_on_last_bar() -> None:
    now = datetime(2026, 8, 28, 20, 22, tzinfo=timezone.utc)
    session_date, after_close = daily_session(now, last_bar_date=date(2026, 8, 27))

    assert session_date == date(2026, 8, 27)
    assert after_close is True


def test_session_window_ends_at_next_open() -> None:
    monday_after_open = datetime(2026, 8, 31, 1, 31, tzinfo=timezone.utc)
    session_date, after_close = daily_session(monday_after_open, last_bar_date=date(2026, 8, 28))

    assert session_date == date(2026, 8, 31)
    assert after_close is False


def test_session_window_before_next_open_stays_on_last_bar() -> None:
    monday_before_open = datetime(2026, 8, 31, 1, 0, tzinfo=timezone.utc)
    session_date, after_close = daily_session(monday_before_open, last_bar_date=date(2026, 8, 28))

    assert session_date == date(2026, 8, 28)
    assert after_close is True


def test_backtest_policy_skips_same_commit_inside_cooldown() -> None:
    should_run, _ = should_run_workflow(
        "backtest",
        [_run(1, "2026-07-16T12:00:00Z")],
        now=NOW,
        head_sha="abc",
        min_hours=24,
    )

    assert should_run is False


def test_backtest_policy_allows_new_commit() -> None:
    should_run, _ = should_run_workflow(
        "backtest",
        [_run(1, "2026-07-17T08:00:00Z", head_sha="old")],
        now=NOW,
        head_sha="new",
    )

    assert should_run is True
