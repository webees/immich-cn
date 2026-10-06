"""文档契约检查：阻止文档与实现再次漂移。

校验四类可机械判定的契约：
1. 文档中出现的 `IMMICH_*` 环境变量必须真的被实现，且实现的环境变量必须被记录；
2. 文档中的 `immich-cn <子命令> [--参数]` 必须存在于 CLI；
3. 文档中的 `make <目标>` 必须存在于 Makefile；
4. 挂载路径与 Immich 版本标签必须匹配
   （< 1.136.0 → /usr/src/app/node_modules/...，>= 1.136.0 → /usr/src/app/server/node_modules/...）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

#: 仅作为构建参数存在、不需要在运行时文档中出现的变量。
BUILD_ONLY = {"IMMICH_BASE", "IMMICH_VERSION", "IMMICH_CN_DATA_DATE"}

DOC_GLOBS = ("README.md", "docs/*.md")
CODE_GLOBS = ("src/**/*.py", "docker/*", "scripts/*", ".github/workflows/*.yml", ".github/*.md", "examples/*.yml")

ENV_PATTERN = re.compile(r"\b(IMMICH_[A-Z0-9_]+)\b")
# 只允许行内空白，避免把「上一行以 immich-cn 结尾、下一行以别的单词开头」误判成子命令
CLI_PATTERN = re.compile(r"(?:^|[ \t`(])immich-cn[ \t]+([a-z-]+)((?:[ \t]+--[a-z-]+)*)", re.MULTILINE)
MAKE_PATTERN = re.compile(r"(?:^|[ \t`(])make[ \t]+([a-z][a-z-]{2,})", re.MULTILINE)
LANGS_PATH = "/i18n-iso-countries/langs"


def _read(paths: list[Path]) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def _expand(patterns: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(Path().glob(pattern)))
    return [path for path in files if path.is_file()]


def _env_names(text: str) -> set[str]:
    return {name for name in ENV_PATTERN.findall(text) if not name.endswith("_")}


def _cli_surface() -> tuple[set[str], set[str]]:
    """从 CLI 解析器提取子命令与全部选项。"""
    sys.path.insert(0, str(Path("src").resolve()))
    from immich_cn.cli import build_parser

    parser = build_parser()
    commands: set[str] = set()
    flags: set[str] = set()
    # argparse 未提供公开的遍历接口，这里直接读取内部结构以获取完整契约
    for action in parser._actions:
        flags.update(action.option_strings)
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                commands.add(name)
                for sub_action in sub._actions:
                    flags.update(sub_action.option_strings)
    return commands, flags


def _make_targets() -> set[str]:
    targets: set[str] = set()
    for line in Path("Makefile").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([a-z][a-z-]*):", line)
        if match:
            targets.add(match.group(1))
    return targets


def check_env(doc_text: str, code_text: str, errors: list[str]) -> None:
    documented = _env_names(doc_text)
    implemented = _env_names(code_text)
    for name in sorted(documented - implemented):
        errors.append(f"文档记录了未实现的环境变量：{name}")
    for name in sorted(implemented - documented - BUILD_ONLY):
        errors.append(f"实现的环境变量未出现在文档中：{name}")


def check_cli(doc_text: str, errors: list[str]) -> None:
    commands, flags = _cli_surface()
    for command, flag_text in CLI_PATTERN.findall(doc_text):
        if command not in commands:
            errors.append(f"文档使用了不存在的子命令：immich-cn {command}")
        for flag in re.findall(r"--[a-z-]+", flag_text):
            if flag not in flags:
                errors.append(f"文档使用了不存在的参数：immich-cn {command} {flag}")


def check_make(doc_text: str, errors: list[str]) -> None:
    targets = _make_targets()
    for target in sorted(set(MAKE_PATTERN.findall(doc_text))):
        if target not in targets:
            errors.append(f"文档使用了不存在的 make 目标：make {target}")


def check_langs_mounts(paths: list[Path], errors: list[str]) -> None:
    """挂载路径必须与其版本标注一致（这是曾经出过错的地方）。"""
    modern = "/usr/src/app/server/node_modules"
    legacy = "/usr/src/app/node_modules"
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if LANGS_PATH not in line:
                continue
            # 只取"最近的一条"版本标注，避免把上一条无关标注算进来（假拒绝）
            annotation = ""
            for previous in range(index - 1, max(-1, index - 4), -1):
                if "1.136" in lines[previous]:
                    annotation = lines[previous]
                    break
            if "< 1.136" in annotation and modern in line:
                errors.append(f"{path}:{index + 1} 标注为 < 1.136.0 却使用了 {modern} 路径")
            if ">= 1.136" in annotation and legacy in line and modern not in line:
                errors.append(f"{path}:{index + 1} 标注为 >= 1.136.0 却使用了 {legacy} 路径")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    doc_files = _expand(DOC_GLOBS)
    code_files = _expand(CODE_GLOBS)
    doc_text = _read(doc_files)
    code_text = _read(code_files)

    errors: list[str] = []
    check_env(doc_text, code_text, errors)
    check_cli(doc_text, errors)
    check_make(doc_text, errors)
    check_langs_mounts(doc_files + _expand(("examples/*.yml",)), errors)

    for error in errors:
        print(f"[!!] {error}")
    if errors:
        print(f"文档契约检查失败：{len(errors)} 项")
        return 1
    if not args.quiet:
        print(f"文档契约检查通过：{len(doc_files)} 个文档、{len(code_files)} 个实现文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
