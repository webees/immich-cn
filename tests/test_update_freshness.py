"""更新新鲜度监控的行为测试：每个状态都必须能被真实输入触发。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.check_update_freshness import (
    UNHEALTHY_STATES,
    _write_github_output,
    evaluate_freshness,
    main,
)
from scripts.cleanup import RunRecord

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
MAX_AGE = timedelta(hours=30)
STALL_GRACE = timedelta(hours=3)


def run_at(
    run_id: int,
    hours_ago: float,
    *,
    status: str = "completed",
    conclusion: str = "success",
    event: str = "schedule",
) -> RunRecord:
    return RunRecord(
        id=run_id,
        name="Auto Data Update",
        status=status,
        created_at=NOW - timedelta(hours=hours_ago),
        head_sha="a" * 40,
        conclusion=conclusion,
        event=event,
    )


def evaluate(runs: list[RunRecord]):
    return evaluate_freshness(runs, now=NOW, max_age=MAX_AGE, stall_grace=STALL_GRACE)


def test_manual_success_cannot_mask_dead_schedule() -> None:
    """负向控制：手动 workflow_dispatch 成功不能证明定时任务还活着。"""
    report = evaluate([run_at(9, 1.0, event="workflow_dispatch"), run_at(8, 90.0, event="schedule")])
    assert report.state == "schedule_stalled"
    assert report.healthy is False
    assert report.schedule_age_hours == pytest.approx(90.0)
    assert "schedule" in report.detail


def test_workflow_without_any_schedule_run_is_flagged() -> None:
    """只有手动触发记录时必须报警，否则「定时更新」从未被验证也看不出问题。"""
    report = evaluate([run_at(9, 1.0, event="workflow_dispatch"), run_at(8, 2.0, event="workflow_dispatch")])
    assert report.state == "schedule_stalled"
    assert report.healthy is False
    assert report.schedule_age_hours is None


def test_manual_success_with_fresh_schedule_is_healthy() -> None:
    """负向控制：手动补跑 + 近期定时触发同时存在时应当是健康的。"""
    report = evaluate([run_at(9, 1.0, event="workflow_dispatch"), run_at(8, 20.0, event="schedule")])
    assert report.state == "ok"
    assert report.healthy is True


def test_no_runs_is_never_run_and_unhealthy() -> None:
    """从未运行过必须是显式状态，不能被当成健康。"""
    report = evaluate([])
    assert report.state == "never_run"
    assert report.healthy is False
    assert report.state in UNHEALTHY_STATES
    assert report.run_id is None


def test_recent_success_is_healthy() -> None:
    report = evaluate([run_at(1, 5.0)])
    assert report.state == "ok"
    assert report.healthy is True
    assert report.run_id == 1
    assert report.conclusion == "success"
    assert report.event == "schedule"


def test_stale_newest_run_is_no_run() -> None:
    """调度不再触发时，即使历史上有成功记录也必须报警。"""
    report = evaluate([run_at(1, 40.0), run_at(2, 400.0)])
    assert report.state == "no_run"
    assert report.healthy is False
    assert "调度" in report.detail


def test_newest_failure_is_failed_even_when_old_success_exists() -> None:
    report = evaluate([run_at(7, 2.0, conclusion="failure"), run_at(6, 26.0)])
    assert report.state == "failed"
    assert report.healthy is False
    assert report.run_id == 7
    assert "failure" in report.detail


def test_long_running_attempt_is_stalled() -> None:
    report = evaluate([run_at(9, 8.0, status="in_progress", conclusion="", event="workflow_dispatch")])
    assert report.state == "stalled"
    assert report.healthy is False
    assert "in_progress" in report.detail


def test_attempt_exactly_at_stall_grace_is_not_stalled() -> None:
    """与 max-age 一样，stall-grace 恰好命中时允许继续，不把边界误判为停摆。"""
    report = evaluate(
        [
            run_at(9, 3.0, status="in_progress", conclusion="", event="schedule"),
            run_at(8, 20.0),
        ]
    )
    assert report.state == "ok"
    assert report.healthy is True
    assert "in_progress" in report.detail


def test_cancelled_run_without_recent_success_is_stale_success() -> None:
    """取消不直接判失败，但也不能掩盖「一直没有成功」的事实。"""
    report = evaluate([run_at(4, 1.0, conclusion="cancelled"), run_at(3, 90.0)])
    assert report.state == "stale_success"
    assert report.healthy is False
    assert report.conclusion == "cancelled"


def test_cancelled_run_with_recent_success_is_healthy() -> None:
    """负向控制：人工取消 + 刚成功过不能被误判为故障。"""
    report = evaluate([run_at(4, 1.0, conclusion="cancelled"), run_at(3, 6.0)])
    assert report.state == "ok"
    assert report.healthy is True


def test_running_without_recent_success_is_stale_success() -> None:
    """负向控制：正在跑不能掩盖长期没有成功。"""
    report = evaluate([run_at(5, 1.0, status="queued", conclusion=""), run_at(3, 200.0)])
    assert report.state == "stale_success"
    assert report.healthy is False


def test_running_within_grace_and_recent_success_is_healthy() -> None:
    report = evaluate([run_at(5, 0.5, status="in_progress", conclusion=""), run_at(3, 20.0)])
    assert report.state == "ok"
    assert report.healthy is True


def test_age_exactly_at_threshold_is_not_flagged() -> None:
    """边界：恰好等于阈值不算超时（``>`` 而不是 ``>=``）。"""
    report = evaluate([run_at(1, 30.0)])
    assert report.state == "ok"


def test_zero_thresholds_are_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_freshness([], now=NOW, max_age=timedelta(0), stall_grace=STALL_GRACE)
    with pytest.raises(ValueError):
        evaluate_freshness([], now=NOW, max_age=MAX_AGE, stall_grace=timedelta(0))


def test_github_output_writes_machine_readable_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """工作流靠 GITHUB_OUTPUT 把状态传给告警步骤，不能悄悄不写。"""
    target = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(target))
    _write_github_output(evaluate([run_at(1, 40.0)]))
    text = target.read_text(encoding="utf-8")
    assert "state=no_run" in text
    assert "healthy=false" in text
    assert "\n\n" not in text


def test_cli_requires_repository() -> None:
    """缺少仓库信息时必须报配置错误，而不是当成健康。"""
    assert main(["--repository", "", "--token", "x"]) == 2
