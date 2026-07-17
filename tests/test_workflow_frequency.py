from datetime import datetime, timezone

from ashare_mainline_radar.workflow_frequency import should_run_workflow

NOW = datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc)


def _run(run_id: int, created_at: str, *, head_sha: str = "abc", conclusion: str = "success") -> dict:
    return {
        "id": run_id,
        "status": "completed",
        "conclusion": conclusion,
        "created_at": created_at,
        "head_sha": head_sha,
    }


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
