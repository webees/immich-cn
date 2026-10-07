"""检查 Auto Data Update 定时任务是否按计划真实执行。

护栏只能证明 workflow 定义正确，不能证明 GitHub 真的触发了 ``schedule``：定时任务
在高负载时会被延迟甚至整天不触发，而「调度没跑」与「跑了但上游无变化」在 Actions
页面看起来完全一样。本脚本把「最近一次运行距今多久 / 最近一次运行结论」变成可判定
的检查项，把静默停摆转成必须处理的告警。

判定状态（互斥且穷尽）：

- ``never_run``：该工作流从未有任何运行记录；
- ``no_run``：最近一次运行的年龄超过 ``--max-age-hours``，调度没有触发；
- ``stalled``：最近一次运行长时间停在未完成状态；
- ``failed``：最近一次已完成运行的结论是失败；
- ``stale_success``：最近一段时间内没有任何成功运行；
- ``schedule_stalled``：最近一段时间内没有 ``schedule`` 事件触发的运行——手动
  ``workflow_dispatch`` 成功不能证明定时任务还活着，因此单独建模；
- ``ok``：以上都不成立。

「人工取消」单独建模：``cancelled`` 是操作者动作，不代表流水线故障，因此不会直接
判失败，但也不会被当作成功——成功新鲜度仍由 ``stale_success`` 单独把关。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.cleanup import CleanupError, GitHubClient, RunRecord

DEFAULT_WORKFLOW = "update-data.yml"
#: 上游调度是每天一次；默认阈值给延迟与重试留出 6 小时余量。
DEFAULT_MAX_AGE_HOURS = 30
DEFAULT_STALL_GRACE_HOURS = 3
#: 人工取消不构成故障信号，只说明这一轮没有产出。
CANCELLED_CONCLUSION = "cancelled"
UNHEALTHY_STATES = ("never_run", "no_run", "stalled", "failed", "stale_success", "schedule_stalled")


@dataclass(frozen=True, slots=True)
class FreshnessReport:
    state: str
    healthy: bool
    detail: str
    age_hours: float | None
    success_age_hours: float | None
    schedule_age_hours: float | None
    run_id: int | None
    conclusion: str
    event: str
    created_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "healthy": self.healthy,
            "detail": self.detail,
            "ageHours": None if self.age_hours is None else round(self.age_hours, 2),
            "successAgeHours": None if self.success_age_hours is None else round(self.success_age_hours, 2),
            "scheduleAgeHours": None if self.schedule_age_hours is None else round(self.schedule_age_hours, 2),
            "runId": self.run_id,
            "conclusion": self.conclusion,
            "event": self.event,
            "createdAt": self.created_at,
        }


def evaluate_freshness(
    runs: Sequence[RunRecord],
    *,
    now: datetime,
    max_age: timedelta,
    stall_grace: timedelta,
) -> FreshnessReport:
    """把运行记录折叠成唯一状态；纯函数，便于负向控制。"""
    if max_age <= timedelta(0):
        raise ValueError("max_age 必须为正数")
    if stall_grace <= timedelta(0):
        raise ValueError("stall_grace 必须为正数")

    ordered = sorted(runs, key=lambda run: run.created_at, reverse=True)
    if not ordered:
        return FreshnessReport("never_run", False, "该工作流没有任何运行记录", None, None, None, None, "", "", "")

    newest = ordered[0]
    age = now - newest.created_at
    age_hours = age.total_seconds() / 3600
    last_success = next((run for run in ordered if run.conclusion == "success"), None)
    success_age_hours = None if last_success is None else (now - last_success.created_at).total_seconds() / 3600
    last_scheduled = next((run for run in ordered if run.event == "schedule"), None)
    schedule_age_hours = None if last_scheduled is None else (now - last_scheduled.created_at).total_seconds() / 3600

    def report(state: str, healthy: bool, detail: str) -> FreshnessReport:
        return FreshnessReport(
            state=state,
            healthy=healthy,
            detail=detail,
            age_hours=age_hours,
            success_age_hours=success_age_hours,
            schedule_age_hours=schedule_age_hours,
            run_id=newest.id,
            conclusion=newest.conclusion,
            event=newest.event,
            created_at=newest.created_at.astimezone(UTC).isoformat(),
        )

    max_age_hours = max_age.total_seconds() / 3600
    if age > max_age:
        return report(
            "no_run",
            False,
            f"最近一次运行在 {age_hours:.1f} 小时前，超过 {max_age_hours:.0f} 小时阈值：调度可能未触发",
        )

    # stalled / failed 直接短路；其余情况（成功、在跑、被取消）都要继续过「成功新鲜度」
    # 与「定时触发新鲜度」两道闸——手动 workflow_dispatch 成功不能证明 schedule 还活着。
    if newest.status != "completed":
        if age > stall_grace:
            return report("stalled", False, f"运行 #{newest.id} 已停留在 {newest.status} 状态 {age_hours:.1f} 小时")
        head = f"运行 #{newest.id} 仍在 {newest.status}（{age_hours:.1f} 小时）"
    elif newest.conclusion != "success" and newest.conclusion != CANCELLED_CONCLUSION:
        return report(
            "failed",
            False,
            f"最近一次运行 #{newest.id} 结论为 {newest.conclusion or 'unknown'}（{age_hours:.1f} 小时前）",
        )
    elif newest.conclusion == CANCELLED_CONCLUSION:
        head = f"最近一次运行 #{newest.id} 被人工取消（{age_hours:.1f} 小时前）"
    else:
        head = f"最近一次运行成功：#{newest.id}，{age_hours:.1f} 小时前（{newest.event}）"

    if success_age_hours is None or success_age_hours > max_age_hours:
        shown = "没有成功记录" if success_age_hours is None else f"最近一次成功在 {success_age_hours:.1f} 小时前"
        return report("stale_success", False, f"{head}，且 {shown}")

    if schedule_age_hours is None:
        return report("schedule_stalled", False, f"{head}；该工作流从未由 schedule 事件触发过")
    if schedule_age_hours > max_age_hours:
        return report(
            "schedule_stalled",
            False,
            f"{head}；最近一次 schedule 触发的运行在 {schedule_age_hours:.1f} 小时前，"
            f"超过 {max_age_hours:.0f} 小时阈值，手动触发成功不能证明定时任务还活着",
        )
    return report(
        "ok",
        True,
        f"{head}，最近一次成功在 {success_age_hours:.1f} 小时前，最近一次定时触发在 {schedule_age_hours:.1f} 小时前",
    )


def _write_github_output(report: FreshnessReport) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"state={report.state}\n")
        handle.write(f"detail={report.detail.replace(chr(10), ' ')}\n")
        handle.write(f"healthy={'true' if report.healthy else 'false'}\n")


def _write_step_summary(report: FreshnessReport, *, repository: str, workflow: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    fields = report.as_dict()
    lines = [
        "## Auto Data Update freshness",
        "",
        f"- repository: `{repository}`",
        f"- workflow: `{workflow}`",
        f"- state: **{report.state}**",
        f"- detail: {report.detail}",
        f"- newest run: `{report.run_id}` created `{report.created_at}` event `{report.event}`",
        f"- newest age: {fields['ageHours']} h; last success age: {fields['successAgeHours']} h;"
        f" last schedule age: {fields['scheduleAgeHours']} h",
        "",
    ]
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _positive_hours(value: str) -> float:
    try:
        hours = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{value!r} 不是数字") from error
    if hours <= 0:
        raise argparse.ArgumentTypeError("小时数必须为正")
    return hours


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--max-age-hours", type=_positive_hours, default=DEFAULT_MAX_AGE_HOURS)
    parser.add_argument("--stall-grace-hours", type=_positive_hours, default=DEFAULT_STALL_GRACE_HOURS)
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.repository or "/" not in args.repository:
        print("::error::需要 --repository OWNER/REPO 或 GITHUB_REPOSITORY", file=sys.stderr)
        return 2
    try:
        client = GitHubClient(args.repository, args.token)
        runs = client.list_workflow_runs(args.workflow, limit=30)
        report = evaluate_freshness(
            runs,
            now=datetime.now(UTC),
            max_age=timedelta(hours=args.max_age_hours),
            stall_grace=timedelta(hours=args.stall_grace_hours),
        )
    except (CleanupError, ValueError) as error:
        print(f"::error::更新新鲜度检查失败：{error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(f"state={report.state} healthy={report.healthy}")
        print(report.detail)

    _write_github_output(report)
    _write_step_summary(report, repository=args.repository, workflow=args.workflow)
    if report.state in UNHEALTHY_STATES:
        print(f"::error::{report.detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
