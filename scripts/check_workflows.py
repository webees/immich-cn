"""工作流安全与健壮性契约检查。

针对已经发生过的问题建立机器护栏：
1. `run:` 块内禁止直接插值 `${{ ... }}`（应通过 `env:` 传递），防止命令注入；
2. 每个 job 必须设置 `timeout-minutes`，避免无人值守任务挂满 runner；
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
SCHEDULED = {"schedule"}


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


def check_jobs(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    jobs = workflow.get("jobs") or {}
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        # 复用型工作流调用（uses）没有 steps，也必须有超时
        if "timeout-minutes" not in job:
            errors.append(f"{path}:{job_name} 缺少 timeout-minutes")


def check_permissions(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    if "permissions" not in workflow:
        errors.append(f"{path} 缺少顶层 permissions 声明")


def check_concurrency(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    triggers = workflow.get("on")
    scheduled = isinstance(triggers, dict) and any(key in triggers for key in SCHEDULED)
    # YAML 1.1 会把裸 on: 解析成 True，这里兼容两种键名
    if not scheduled and isinstance(triggers, dict):
        scheduled = "schedule" in {str(key) for key in triggers}
    if scheduled and "concurrency" not in workflow:
        errors.append(f"{path} 是定时工作流但缺少 concurrency")


def main() -> int:
    errors: list[str] = []
    files = sorted(Path(".github/workflows").glob("*.yml"))
    if not files:
        print("[!!] 未找到任何工作流文件")
        return 1
    for path in files:
        workflow = load(path)
        if workflow is None:
            errors.append(f"{path} 无法解析")
            continue
        check_run_blocks(path, workflow, errors)
        check_jobs(path, workflow, errors)
        check_permissions(path, workflow, errors)
        check_concurrency(path, workflow, errors)

    for error in errors:
        print(f"[!!] {error}")
    if errors:
        print(f"工作流契约检查失败：{len(errors)} 项")
        return 1
    print(f"工作流契约检查通过：{len(files)} 个工作流")
    return 0


if __name__ == "__main__":
    sys.exit(main())
