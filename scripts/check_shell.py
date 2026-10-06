"""Shell 脚本与工作流 run 块的静态检查。

当前规则（均来自真实缺陷）：
1. `$VAR` 紧跟非 ASCII 字符时必须写成 `${VAR}`。
   在 UTF-8 locale 下 bash 会把多字节字符当作变量名的一部分，
   于是 `$target，` 实际引用的是 `target，`，配合 `set -u` 直接报
   “unbound variable”，把原本的错误提示吞掉。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

SHELL_SUFFIXES = {".sh"}
VARIABLE = re.compile(rb"\$[A-Za-z_][A-Za-z0-9_]*")


def scan_text(path: Path, text: str, errors: list[str]) -> None:
    for number, line in enumerate(text.splitlines(), start=1):
        raw = line.encode("utf-8")
        for match in VARIABLE.finditer(raw):
            end = match.end()
            if end < len(raw) and raw[end] >= 0x80:
                name = match.group().decode("ascii", errors="replace")
                errors.append(
                    f"{path}:{number} `{name}` 紧跟非 ASCII 字符，bash 会把它并入变量名；请写成 ${{{name[1:]}}}"
                )

    # CLI 参数必须在文件注释里说明，否则用户只能读代码才能发现（--geodata-only 曾如此）
    documented = {
        flag
        for line in text.splitlines()
        if line.lstrip().startswith("#")
        for flag in re.findall(r"--[a-z][a-z-]+", line)
    }
    for flag in sorted(set(re.findall(r"^\s+(--[a-z][a-z-]+)\)", text, re.MULTILINE))):
        if flag not in documented:
            errors.append(f"{path} 实现了 {flag}，但注释里没有说明用法")


def shell_files() -> list[Path]:
    files = list(Path("docker").glob("*.sh")) + list(Path("scripts").glob("*.sh"))
    return sorted(files)


def workflow_files() -> list[Path]:
    return sorted(Path(".github/workflows").glob("*.yml"))


def main() -> int:
    errors: list[str] = []

    for path in shell_files():
        scan_text(path, path.read_text(encoding="utf-8"), errors)

    for path in workflow_files():
        try:
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            errors.append(f"{path} YAML 解析失败：{error}")
            continue
        for job_name, job in (workflow.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for index, step in enumerate(job.get("steps") or [], start=1):
                if not isinstance(step, dict) or "run" not in step:
                    continue
                label = step.get("name", f"step#{index}")
                scan_text(Path(f"{path}:{job_name}/{label}"), str(step["run"]), errors)

    for error in errors:
        print(f"[!!] {error}")
    if errors:
        print(f"Shell 契约检查失败：{len(errors)} 项")
        return 1
    print(f"Shell 契约检查通过：{len(shell_files())} 个脚本、{len(workflow_files())} 个工作流")
    return 0


if __name__ == "__main__":
    sys.exit(main())
