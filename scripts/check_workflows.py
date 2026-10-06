"""工作流安全与健壮性契约检查。

针对已经发生过的问题建立机器护栏：
1. `run:` 块内禁止直接插值 `${{ ... }}`（应通过 `env:` 传递），防止命令注入；
2. 普通 job 必须设置 `timeout-minutes`；调用 reusable workflow 的 job 反之**不允许**
   出现 `timeout-minutes`/`runs-on`/`steps`（GitHub 会直接拒绝解析整个工作流）；
3. 工作流必须声明顶层 `permissions`，保持最小权限；
4. 定时工作流必须设置 `concurrency`，防止重叠执行。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - 依赖已在 dev extra 中声明
    print("缺少 PyYAML，请先执行：pip install -e '.[dev]'")
    sys.exit(2)

INTERPOLATION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)
ACTION_SHA = re.compile(r"[0-9a-f]{40}")
RELEASE_DELETE = re.compile(r"\bgh release delete\s+([A-Za-z0-9._-]+)")
RELEASE_CREATE = re.compile(r"\bgh release create\s+([A-Za-z0-9._-]+)")
RELEASE_EDIT = re.compile(r"\bgh release edit\s+([A-Za-z0-9._-]+)")
RELEASE_UPLOAD = re.compile(r"\bgh release upload\s+([A-Za-z0-9._-]+)")
SCHEDULED = {"schedule"}
#: 这些函数是运行级聚合判断，已经涵盖全部依赖的结果，因此不受"依赖覆盖"规则约束。
#: 注意不能把 cancelled() 算进来：它只表示"是否被取消"，并不反映依赖是否失败，
#: `!cancelled()` 实际等价于 always()，配合部分 needs 判断时仍会漏掉失败分支。
GLOBAL_STATUS_FUNCTIONS = ("failure()", "success()", "always()")


def load(path: Path) -> dict[str, Any] | None:
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:  # pragma: no cover - YAML 由 CI 直接暴露
        print(f"[!!] {path}: YAML 解析失败：{error}")
        return None
    return parsed if isinstance(parsed, dict) else None


def check_run_blocks(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for index, step in enumerate(job.get("steps") or [], start=1):
            if not isinstance(step, dict) or "run" not in step:
                continue
            script = str(step["run"])
            found = INTERPOLATION.findall(script)
            if found:
                name = step.get("name", f"step#{index}")
                errors.append(f"{path}:{job_name}/{name} 的 run 块直接插值 {found[0]}，应改用 env")


#: 调用 reusable workflow 的 job 允许出现的键（GitHub 的 schema 限制）
REUSABLE_JOB_KEYS = {"name", "uses", "with", "secrets", "strategy", "needs", "if", "concurrency", "permissions"}


def check_jobs(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    jobs = workflow.get("jobs") or {}
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        if "uses" in job:
            illegal = sorted(set(job) - REUSABLE_JOB_KEYS)
            if illegal:
                errors.append(
                    f"{path}:{job_name} 调用 reusable workflow，不允许出现 {illegal}；"
                    "GitHub 会拒绝解析整个工作流（例如 timeout-minutes 只能放在被调用工作流的 job 上）"
                )
            continue
        if "timeout-minutes" not in job:
            errors.append(f"{path}:{job_name} 缺少 timeout-minutes")


def check_permissions(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    if "permissions" not in workflow:
        errors.append(f"{path} 缺少顶层 permissions 声明")


def check_action_pins(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """外部 Action 必须固定到完整 commit SHA，不能使用可重定向的标签。"""

    def validate(value: object, location: str) -> None:
        if not isinstance(value, str) or value.startswith("./") or value.startswith("docker://"):
            return
        _, separator, revision = value.rpartition("@")
        if not separator or not ACTION_SHA.fullmatch(revision):
            errors.append(f"{path}:{location} 的 Action {value!r} 未固定到 40 位 commit SHA")

    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        if "uses" in job:
            validate(job["uses"], job_name)
        for index, step in enumerate(job.get("steps") or [], start=1):
            if isinstance(step, dict) and "uses" in step:
                validate(step["uses"], f"{job_name}/step#{index}")


def check_release_replacements(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """同名 Release 不得先删除再创建，否则创建失败会直接造成发布空窗。"""
    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for index, step in enumerate(job.get("steps") or [], start=1):
            if not isinstance(step, dict) or "run" not in step:
                continue
            script = str(step["run"])
            deleted = set(RELEASE_DELETE.findall(script))
            created = set(RELEASE_CREATE.findall(script))
            for tag in sorted(deleted & created):
                errors.append(
                    f"{path}:{job_name}/step#{index} 对 Release {tag!r} 先删除后重建；"
                    "创建失败会造成发布空窗，应原地 edit/upload"
                )


def check_release_update_order(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """滚动 Release 必须先替换资产，再更新标题/说明，避免资产失败后元数据谎报新版本。"""
    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for index, step in enumerate(job.get("steps") or [], start=1):
            if not isinstance(step, dict) or "run" not in step:
                continue
            script = str(step["run"])
            edited = set(RELEASE_EDIT.findall(script))
            uploaded = set(RELEASE_UPLOAD.findall(script))
            for tag in sorted(edited & uploaded):
                edit_at = script.find(f"gh release edit {tag}")
                upload_at = script.find(f"gh release upload {tag}")
                if edit_at < upload_at:
                    errors.append(
                        f"{path}:{job_name}/step#{index} 对 Release {tag!r} 在替换资产前更新了元数据；"
                        "upload 失败时标题会谎报新版本"
                    )


def check_concurrency(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    triggers = workflow.get("on")
    scheduled = isinstance(triggers, dict) and any(key in triggers for key in SCHEDULED)
    # YAML 1.1 会把裸 on: 解析成 True，这里兼容两种键名
    if not scheduled and isinstance(triggers, dict):
        scheduled = "schedule" in {str(key) for key in triggers}
    if scheduled and "concurrency" not in workflow:
        errors.append(f"{path} 是定时工作流但缺少 concurrency")


def check_needs_coverage(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """用 `if` 判断依赖结果时，必须判断**全部**依赖。

    只判断部分依赖（例如只写 `needs.build.result` 却漏了 `needs.release`），
    一旦被遗漏的依赖失败，该任务仍会照常运行——典型的失败路径缺陷。
    使用 failure()/success()/always()/cancelled() 的运行级判断不受此规则约束。
    """
    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        needs = job.get("needs")
        if not needs:
            continue
        needed = [needs] if isinstance(needs, str) else list(needs)
        condition = str(job.get("if", ""))
        if not condition or "needs." not in condition:
            continue
        if any(function in condition for function in GLOBAL_STATUS_FUNCTIONS):
            continue
        missing = [name for name in needed if f"needs.{name}." not in condition]
        if missing:
            errors.append(f"{path}:{job_name} 的 if 只判断了部分依赖，遗漏 {missing}；被遗漏的依赖失败时该任务仍会运行")


def check_issue_search_scope(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """自动化 issue 的标题搜索必须限定 automation 标签，避免误改用户 issue。"""
    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for index, step in enumerate(job.get("steps") or [], start=1):
            if not isinstance(step, dict) or "run" not in step:
                continue
            script = str(step["run"])
            if (
                "gh issue list" in script
                and "自动更新数据失败 in:title" in script
                and "--label automation" not in script
            ):
                errors.append(
                    f"{path}:{job_name}/step#{index} 的自动化 issue 标题搜索未限定 automation 标签，"
                    "可能误改或误关用户 issue"
                )


def _workflow_call_outputs(workflow: dict[str, Any]) -> set[str]:
    triggers = workflow.get("on")
    if not isinstance(triggers, dict):
        legacy = workflow.get(True)
        triggers = legacy if isinstance(legacy, dict) else {}
    call = triggers.get("workflow_call") if isinstance(triggers, dict) else None
    outputs = (call or {}).get("outputs") if isinstance(call, dict) else None
    return set(outputs) if isinstance(outputs, dict) else set()


def check_references(
    path: Path,
    workflow: dict[str, Any],
    errors: list[str],
    outputs_by_workflow: dict[str, set[str]],
) -> None:
    """检查 output 引用是否悬空。

    引用不存在的 step id、或引用被调用工作流未声明的 output 时，表达式会**静默求值为空**，
    下游拿到空值却不会报错——典型的静默失败。
    """
    dangling: set[str] = set()
    missing_outputs: set[str] = set()
    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        text = yaml.safe_dump(job, allow_unicode=True)
        step_ids = {step.get("id") for step in (job.get("steps") or []) if isinstance(step, dict) and step.get("id")}
        for step_id in re.findall(r"steps\.([A-Za-z0-9_-]+)\.outputs\.", text):
            if step_id not in step_ids:
                dangling.add(f"{job_name} -> steps.{step_id}.outputs")
        for ref_job, output in set(re.findall(r"needs\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)", text)):
            target = (workflow.get("jobs", {}).get(ref_job) or {}).get("uses")
            if not target:
                continue  # 普通 job 的输出在本文件内声明，另有校验
            called = str(target).split("/")[-1]
            if output not in outputs_by_workflow.get(called, set()):
                missing_outputs.add(f"{job_name} -> needs.{ref_job}.outputs.{output}（{called} 未声明）")

    for item in sorted(dangling):
        errors.append(f"{path}: 引用了不存在的 step id：{item}")
    for item in sorted(missing_outputs):
        errors.append(f"{path}: 引用了被调用工作流未声明的输出：{item}")


def main() -> int:
    errors: list[str] = []
    files = sorted(Path(".github/workflows").glob("*.yml"))
    if not files:
        print("[!!] 未找到任何工作流文件")
        return 1
    loaded: dict[str, dict[str, Any]] = {}
    for path in files:
        workflow = load(path)
        if workflow is None:
            errors.append(f"{path} 无法解析")
            continue
        loaded[path.name] = workflow
    outputs_by_workflow = {name: _workflow_call_outputs(workflow) for name, workflow in loaded.items()}

    for path in files:
        workflow = loaded.get(path.name)
        if workflow is None:
            continue
        check_run_blocks(path, workflow, errors)
        check_jobs(path, workflow, errors)
        check_permissions(path, workflow, errors)
        check_action_pins(path, workflow, errors)
        check_release_replacements(path, workflow, errors)
        check_release_update_order(path, workflow, errors)
        check_concurrency(path, workflow, errors)
        check_needs_coverage(path, workflow, errors)
        check_issue_search_scope(path, workflow, errors)
        check_references(path, workflow, errors, outputs_by_workflow)

    for error in errors:
        print(f"[!!] {error}")
    if errors:
        print(f"工作流契约检查失败：{len(errors)} 项")
        return 1
    print(f"工作流契约检查通过：{len(files)} 个工作流")
    return 0


if __name__ == "__main__":
    sys.exit(main())
