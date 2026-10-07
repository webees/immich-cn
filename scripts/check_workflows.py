"""工作流安全与健壮性契约检查。

针对已经发生过的问题建立机器护栏：
1. `run:` 块内禁止直接插值 `${{ ... }}`（应通过 `env:` 传递），防止命令注入；
2. 普通 job 必须设置 `timeout-minutes`；调用 reusable workflow 的 job 反之**不允许**
   出现 `timeout-minutes`/`runs-on`/`steps`（GitHub 会直接拒绝解析整个工作流）；
3. 工作流必须声明顶层 `permissions`，保持最小权限；
4. 定时工作流必须设置 `concurrency`，防止重叠执行；
5. `hashFiles('...')` 里的固定路径必须真实存在——`hashFiles` 对不存在的路径返回空字符串，
   会让缓存键的该维度静默消失（真实事故：`config.py` 改名 `settings.py` 后缓存键出现 `--`）；
6. `actions/checkout` 必须设置 `persist-credentials: false`，避免 token 留在 `.git/config`
   被后续步骤读取；
7. CONTRIBUTING.md 声明的 required check 必须是某个 pull_request 工作流真实产生的 job 名，
   且不能由多个工作流同名产生。
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
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
HASH_FILES_CALL = re.compile(r"hashFiles\(([^)]*)\)")
HASH_FILES_ARG = re.compile(r"['\"]([^'\"]+)['\"]")
#: 含这些字符的参数按 glob 处理，不要求字面路径存在。
GLOB_CHARS = "*?[]"
#: CONTRIBUTING.md 中列出 required check 的引导语与 job 名里的 matrix 占位符。
REQUIRED_CHECK_HEADER = "必须通过以下状态检查"
NAME_MATRIX_EXPR = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")


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
    permissions = workflow.get("permissions")
    if permissions is None:
        errors.append(f"{path} 缺少顶层 permissions 声明")
        return
    if isinstance(permissions, str):
        if permissions == "write-all":
            errors.append(f"{path} 顶层 permissions 使用 write-all，权限范围过大")
        return
    if isinstance(permissions, dict):
        broad = sorted(scope for scope, value in permissions.items() if value == "write")
        if broad:
            errors.append(f"{path} 顶层 permissions 含 write：{broad}；应下沉到具体 job")


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


def check_snapshot_immutability(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """同日后续发布不得覆盖 data-YYYY-MM-DD，必须落到不可变 revision tag。"""
    if path.name != "update-data.yml":
        return
    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for index, step in enumerate(job.get("steps") or [], start=1):
            if not isinstance(step, dict) or "run" not in step:
                continue
            script = str(step["run"])
            if 'gh release view "data-${DATE}"' not in script:
                continue
            if "-sha-${short_sha}" not in script:
                errors.append(
                    f"{path}:{job_name}/step#{index} 的日期快照冲突分支未创建 data-DATE-sha-短提交；"
                    "同日修订会丢失或覆盖不可变快照"
                )
            if re.search(r"gh release upload\s+\"data-\$\{DATE\}\"[^\n]*--clobber", script):
                errors.append(
                    f"{path}:{job_name}/step#{index} 使用 --clobber 覆盖 data-${{DATE}}；不可变日期快照不能被改写"
                )


def check_image_supply_chain(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """镜像发布必须保留 digest 冒烟、Trivy 扫描和 keyless 签名。"""
    if path.name != "_build-data.yml":
        return
    text = yaml.safe_dump(workflow, allow_unicode=True)
    if text.count("docker pull") < 2:
        errors.append(f"{path} 缺少数据或 server 镜像的最终 digest 冒烟验证")
    if "完整 Immich 服务栈冒烟" not in text or "Geodata import completed" not in text:
        errors.append(f"{path} 缺少 PostgreSQL/Redis/Immich 完整服务栈导入冒烟")
    if text.count("aquasecurity/setup-trivy@") < 1 or text.count("trivy image") < 5:
        errors.append(f"{path} 缺少数据或 server 镜像的 Trivy 漏洞/许可证扫描")
    if text.count("comm -13") < 1 or "trivy-server-base-vuln.tsv" not in text:
        errors.append(f"{path} 缺少 server 覆盖镜像相对官方基础镜像的漏洞差集检查")
    if text.count("cosign sign --yes") < 2:
        errors.append(f"{path} 缺少数据或 server 镜像的 Cosign keyless 签名")
    if text.count("imagetools create") < 1 or text.count("${IMAGE_VERSION}") < 2:
        errors.append(f"{path} 缺少数据与 server 镜像的语义化版本标签")
    if (
        text.count("org.opencontainers.image.version=${{ steps.tool.outputs.version }}") < 1
        or text.count("org.opencontainers.image.version=${TOOL_VERSION}") < 1
        or text.count("org.immich-cn.data-date") < 2
    ):
        errors.append(f"{path} OCI version 未使用项目版本，或缺少独立的数据日期标签")
    if "org.opencontainers.image.licenses=AGPL-3.0-only AND MIT" not in text:
        errors.append(f"{path} server 组合镜像未声明 AGPL-3.0-only AND MIT")


def check_version_release(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """版本化 Release 必须把同一版本传递给两个镜像，并在构建前检查占用。"""
    if path.name != "release.yml":
        return
    text = path.read_text(encoding="utf-8")
    if "needs: validate" not in text or "docker manifest inspect" not in text:
        errors.append(f"{path} 缺少版本 Release 的预检查；重复版本可能在构建后失败并覆盖镜像标签")
    if "image-version: ${{ inputs.version }}" not in text:
        errors.append(f"{path} 未把 Release 版本传递给镜像构建")
    if "tomllib" not in text or "repo_version=" not in text:
        errors.append(f"{path} 缺少输入版本与 pyproject.toml 的一致性检查")
    validate = (workflow.get("jobs") or {}).get("validate")
    steps = validate.get("steps") if isinstance(validate, dict) else None
    if not isinstance(steps, list) or not any(
        isinstance(step, dict) and str(step.get("uses", "")).startswith("actions/checkout@") for step in steps
    ):
        errors.append(f"{path}:validate 缺少 checkout，无法读取 pyproject.toml 校验版本")


def check_cleanup_workflow(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """定时清理必须默认 apply、支持 prune-all，并具备所需最小权限。"""
    if path.name != "cleanup.yml":
        return
    text = yaml.safe_dump(workflow, allow_unicode=True)
    if "scripts/cleanup.py" not in text or "--prune-all" not in text:
        errors.append(f"{path} 缺少清理脚本或稳定前 prune-all 入口")
    if "APPLY: ${{ github.event_name == 'schedule' || inputs.apply }}" not in text:
        errors.append(f"{path} 定时任务没有自动切换为 apply")
    if "actions: write" not in text or "packages: write" not in text or "contents: write" not in text:
        errors.append(f"{path} 缺少 Actions/Release/Packages 清理所需权限")


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


def check_failure_notifier_coverage(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """failure() 通知必须覆盖所有不会反向依赖它的 job。"""
    jobs = workflow.get("jobs") or {}
    notifier = jobs.get("notify-failure")
    if not isinstance(notifier, dict) or "failure()" not in str(notifier.get("if", "")):
        return
    raw_needs = notifier.get("needs")
    needs = {raw_needs} if isinstance(raw_needs, str) else set(raw_needs or [])
    expected: set[str] = set()
    for name, job in jobs.items():
        if name == "notify-failure" or not isinstance(job, dict):
            continue
        job_needs = job.get("needs")
        downstream = {job_needs} if isinstance(job_needs, str) else set(job_needs or [])
        if "notify-failure" not in downstream:
            expected.add(name)
    missing = sorted(expected - needs)
    if missing:
        errors.append(f"{path}:notify-failure 的 needs 未覆盖 {missing}，这些 job 失败时不会创建告警")


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


def _iter_strings(value: Any) -> Iterator[str]:
    """递归产出 YAML 结构中的全部字符串。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def _job_names(workflow: dict[str, Any]) -> list[str]:
    """展开 job 名称中的 matrix 模板，得到会真实出现在 check 列表里的名字。"""
    names: list[str] = []
    for job in (workflow.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        raw = job.get("name")
        if not isinstance(raw, str):
            continue
        strategy = job.get("strategy")
        matrix = (strategy or {}).get("matrix") if isinstance(strategy, dict) else None
        placeholders = NAME_MATRIX_EXPR.findall(raw)
        if not placeholders:
            names.append(raw)
            continue
        values = [raw]
        for key in placeholders:
            options = matrix.get(key) if isinstance(matrix, dict) else None
            if not isinstance(options, list) or not options:
                values = []
                break
            pattern = re.compile(r"\$\{\{\s*matrix\." + re.escape(key) + r"\s*\}\}")
            values = [pattern.sub(str(option), value) for value in values for option in options]
        names.extend(values)
    return names


def _documented_required_checks() -> list[str]:
    """读取 CONTRIBUTING.md 中"必须通过以下状态检查"下的列表项。"""
    text = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
    if REQUIRED_CHECK_HEADER not in text:
        return []
    items: list[str] = []
    for line in text.split(REQUIRED_CHECK_HEADER, 1)[1].splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            if items:
                break
            continue
        value = stripped[2:].strip().strip("`")
        if value:
            items.append(value)
    return items


def check_required_check_names(
    loaded: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    """required check 名必须是真实存在、唯一、且由 pull_request 工作流产生。"""
    produced: dict[str, list[str]] = {}
    pr_workflows: set[str] = set()
    for name, workflow in loaded.items():
        triggers = workflow.get("on")
        if not isinstance(triggers, dict):
            legacy = workflow.get(True)
            triggers = legacy if isinstance(legacy, dict) else {}
        if "pull_request" in triggers:
            pr_workflows.add(name)
        for job_name in _job_names(workflow):
            produced.setdefault(job_name, []).append(name)

    documented = _documented_required_checks()
    if not documented:
        errors.append(f"CONTRIBUTING.md 未列出任何 required check（缺少“{REQUIRED_CHECK_HEADER}”列表），护栏可能已失效")
        return
    for item in documented:
        owners = produced.get(item, [])
        if not owners:
            errors.append(f"CONTRIBUTING.md 声明的 required check {item!r} 没有任何工作流 job 会产生")
        elif len(owners) > 1:
            errors.append(f"required check {item!r} 由多个工作流产生：{', '.join(sorted(owners))}，存在同名混淆风险")
        elif owners[0] not in pr_workflows:
            errors.append(
                f"required check {item!r} 由 {owners[0]} 产生，但该工作流没有 pull_request 触发，PR 上不会出现"
            )


def check_published_url_verification(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """发布流程必须自检文档承诺的固定下载地址。

    README 与部署文档都写了 `releases/latest/download/<canonical 名>`；一旦 latest
    指向别的 Release 或资产改名，用户照着文档就会 404，而发布流程本身仍然全绿。
    """
    if path.name != "update-data.yml":
        return
    if "releases/latest/download/" not in yaml.safe_dump(workflow, allow_unicode=True):
        errors.append(f"{path} 未在发布后验证文档中的固定下载地址（releases/latest/download/…）")


def check_examples_compose_validation(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """CI 必须真实解析 examples/ 的 compose 文件。

    文档让用户直接复制这些文件，只做 YAML 语法检查抓不到错误挂载路径、
    缺失 env_file 或写错的镜像名；必须用 `docker compose config` 走一遍官方规范。
    """
    if path.name != "ci.yml":
        return
    # PyYAML 会把长 run 字符串折行，直接检查原始文本才能匹配准确的 shell 片段。
    del workflow
    text = path.read_text(encoding="utf-8")
    if "docker compose -f" not in text:
        errors.append(f"{path} 未用 docker compose config 校验 examples/，文档示例可能悄悄失效")
        return
    examples = path.parents[2] / "examples"
    compose_files = sorted(examples.glob("compose.*.yml"))
    if not compose_files:
        errors.append(f"{path} 的 CI 未发现任何 examples/compose.*.yml，compose 校验可能已失效")
    if "examples/compose.*.yml" not in text or 'for path in "$workdir"/compose.*.yml' not in text:
        errors.append(
            f"{path} 未用 examples/compose.*.yml 通配符覆盖全部 compose 示例，"
            "新增示例可能不会被 docker compose config 校验"
        )
    nginx_config = examples / "nginx" / "immich-cn.conf"
    if nginx_config.exists() and ("nginx -t" not in text or nginx_config.name not in text):
        errors.append(f"{path} 未用 nginx -t 校验 {nginx_config.relative_to(examples.parent)}")


def check_image_size_budget(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """CI 必须给出镜像尺寸预算，并阻止冗余语言包重新进入镜像。"""
    if path.name != "ci.yml":
        return
    del workflow
    text = path.read_text(encoding="utf-8")
    required = (
        "镜像尺寸预算",
        "IMAGE_SIZE_BUDGET_BYTES",
        "docker image inspect immich-cn-geodata:ci",
        "docker image inspect immich-cn-server:ci",
        "/opt/immich-cn/i18n-iso-countries/langs/zh.json",
    )
    missing = [token for token in required if token not in text]
    if missing:
        errors.append(f"{path} 缺少镜像尺寸或语言包最小化护栏：{'、'.join(missing)}")


def check_checkout_credentials(path: Path, workflow: dict[str, Any], errors: list[str]) -> int:
    """每个 actions/checkout 都必须关闭凭据持久化，返回发现的 checkout 数量。

    checkout 默认把 token 写入 `.git/config`，后续任意步骤（含第三方 Action）都能读到；
    这些工作流全部通过 `gh` + `GH_TOKEN` 访问 GitHub API，不需要本地 git 凭据。
    """
    found = 0
    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for index, step in enumerate(job.get("steps") or [], start=1):
            if not isinstance(step, dict):
                continue
            if not str(step.get("uses") or "").startswith("actions/checkout@"):
                continue
            found += 1
            options = step.get("with")
            value = options.get("persist-credentials") if isinstance(options, dict) else None
            # YAML `false` 与字符串 "false"（actions/getBooleanInput 均接受）都算合规
            if value is False or (isinstance(value, str) and value.strip().lower() == "false"):
                continue
            name = step.get("name", f"step#{index}")
            errors.append(
                f"{path}:{job_name}/{name} 的 actions/checkout 未设置 persist-credentials: false，"
                "token 会被写入 .git/config 供后续步骤读取"
            )
    return found


def check_hash_files_paths(path: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    """`hashFiles('...')` 里的固定路径必须存在。

    `hashFiles` 对不存在的路径返回空字符串，缓存键的该维度会静默消失。
    真实事故：`src/immich_cn/config.py` 改名 `settings.py` 后缓存键变成
    `immich-cn-sources-Linux-1.0.4--<run_id>`，上游配置变化不再使缓存键失效。
    """
    for text in _iter_strings(workflow):
        calls = HASH_FILES_CALL.findall(text)
        if text.count("hashFiles(") and not calls:
            errors.append(f"{path}: 无法解析 hashFiles 调用，护栏可能已失效")
        for arguments in calls:
            candidates = HASH_FILES_ARG.findall(arguments)
            if not candidates:
                errors.append(f"{path}: hashFiles 参数里没有可解析的路径：{arguments!r}")
            for candidate in candidates:
                if any(char in candidate for char in GLOB_CHARS):
                    continue
                if not Path(candidate).exists():
                    errors.append(f"{path}: hashFiles 引用了不存在的路径 {candidate!r}，该缓存键维度会静默变成空字符串")


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

    checkout_total = 0
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
        check_snapshot_immutability(path, workflow, errors)
        check_image_supply_chain(path, workflow, errors)
        check_version_release(path, workflow, errors)
        check_cleanup_workflow(path, workflow, errors)
        check_concurrency(path, workflow, errors)
        check_needs_coverage(path, workflow, errors)
        check_issue_search_scope(path, workflow, errors)
        check_failure_notifier_coverage(path, workflow, errors)
        check_references(path, workflow, errors, outputs_by_workflow)
        check_hash_files_paths(path, workflow, errors)
        checkout_total += check_checkout_credentials(path, workflow, errors)
        check_examples_compose_validation(path, workflow, errors)
        check_image_size_budget(path, workflow, errors)
        check_published_url_verification(path, workflow, errors)

    if checkout_total == 0:
        errors.append("未在任何工作流中找到 actions/checkout 步骤，凭据持久化护栏可能已失效")
    check_required_check_names(loaded, errors)

    for error in errors:
        print(f"[!!] {error}")
    if errors:
        print(f"工作流契约检查失败：{len(errors)} 项")
        return 1
    print(f"工作流契约检查通过：{len(files)} 个工作流")
    return 0


if __name__ == "__main__":
    sys.exit(main())
