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

#: 参与契约检查的文档（含贡献指南与安全策略，它们同样会引用路径与命令）
DOC_GLOBS = ("README.md", "docs/*.md", "CONTRIBUTING.md", "SECURITY.md")
CODE_GLOBS = ("src/**/*.py", "docker/*", "scripts/*", ".github/workflows/*.yml", ".github/*.md", "examples/*.yml")

ENV_PATTERN = re.compile(r"\b(IMMICH_[A-Z0-9_]+)\b")
# 只允许行内空白，避免把「上一行以 immich-cn 结尾、下一行以别的单词开头」误判成子命令
CLI_PATTERN = re.compile(r"(?:^|[ \t`(])immich-cn[ \t]+([a-z-]+)((?:[ \t]+--[a-z-]+)*)", re.MULTILINE)
MAKE_PATTERN = re.compile(r"(?:^|[ \t`(])make[ \t]+([a-z][a-z-]{2,})", re.MULTILINE)
LANGS_PATH = "/i18n-iso-countries/langs"
FIRST_DOWNLOAD_MIB = 260

#: 价值完全依赖"能被找到"的文件：必须在 README 或 docs 中被引用，否则等于隐藏文件。
DISCOVERABLE_GLOBS = ("NOTICE", "examples/*.yml", "docs/*.md")

#: 文档里以这些后缀出现的反引号路径必须是仓库中真实存在的文件
FILE_SUFFIXES = (".py", ".sh", ".toml", ".json", ".yml", ".yaml", ".md", ".cff", ".cfg", ".txt")
#: 这些前缀指向生成物、归档内部路径或外部仓库，不按仓库文件校验
RUNTIME_PATH_PREFIXES = (
    "build/",
    "dist/",
    ".cache/",
    "work/",
    "outputs/",
    "geodata/",
    "i18n-iso-countries/",
    "releases/",
    "package/",
    "/",
    "http",
    "ghcr.io",
)


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


def check_discoverable(errors: list[str]) -> None:
    """关键文件必须至少被 README 或某个 docs 文档引用一次。"""
    readme = Path("README.md")
    roots = [readme, *sorted(Path("docs").glob("*.md"))]
    root_texts = {path: path.read_text(encoding="utf-8") for path in roots if path.exists()}
    for pattern in DISCOVERABLE_GLOBS:
        for path in sorted(Path().glob(pattern)):
            if not path.is_file():
                continue
            others = "\n".join(text for root, text in root_texts.items() if root != path)
            if path.name not in others and str(path) not in others:
                errors.append(f"{path} 未被 README 或 docs 引用（用户无法发现）")


def check_numeric_contracts(errors: list[str]) -> None:
    """文档里的数字必须与实现一致（变体数、定时时刻、快照保留数量）。"""
    sys.path.insert(0, str(Path("src").resolve()))
    from immich_cn.config import DEFAULT_PATTERNS
    from immich_cn.package import build_variants

    doc_text = _read(_expand(DOC_GLOBS))
    workflow = Path(".github/workflows/update-data.yml").read_text(encoding="utf-8")
    makefile = Path("Makefile").read_text(encoding="utf-8")

    expected_variants = len(build_variants(DEFAULT_PATTERNS))
    for match in re.finditer(r"(\d+)\s*个制品", doc_text):
        if int(match.group(1)) != expected_variants:
            errors.append(f"文档称 {match.group(1)} 个制品，实际生成 {expected_variants} 个")

    cron = re.search(r'cron:\s*"(\d+)\s+(\d+)', workflow)
    if cron:
        minute, hour = int(cron.group(1)), int(cron.group(2))
        for match in re.finditer(r"UTC (\d{1,2}):(\d{2})", doc_text):
            if (int(match.group(1)), int(match.group(2))) != (hour, minute):
                errors.append(f"文档称 UTC {match.group(1)}:{match.group(2)}，实际 cron 为 {hour:02d}:{minute:02d}")
        beijing = (hour + 8) % 24
        for match in re.finditer(r"北京时间 (\d{1,2}):(\d{2})", doc_text):
            if (int(match.group(1)), int(match.group(2))) != (beijing, minute):
                errors.append(f"文档称北京时间 {match.group(1)}:{match.group(2)}，实际为 {beijing:02d}:{minute:02d}")

    retention = re.search(r"snapshot-retention:.*?default:\s*(\d+)", workflow, re.DOTALL)
    if retention:
        expected = int(retention.group(1))
        for match in re.finditer(r"保留最近 (\d+) 个", doc_text):
            if int(match.group(1)) != expected:
                errors.append(f"文档称保留最近 {match.group(1)} 个快照，实际默认 {expected}")

    make_download = re.search(r"build:.*?约\s*(\d+)\s*MiB", makefile)
    if not make_download:
        errors.append("Makefile 的 build 帮助未标注首次下载体积")
    elif int(make_download.group(1)) != FIRST_DOWNLOAD_MIB:
        errors.append(f"Makefile 称首次下载约 {make_download.group(1)} MiB，实际压缩下载约 {FIRST_DOWNLOAD_MIB} MiB")


def check_referenced_paths(doc_files: list[Path], errors: list[str]) -> None:
    """文档中引用的仓库文件必须真实存在（防止重构后路径静默失效）。"""
    inline = re.compile(r"`([^`\s]+)`")
    for path in doc_files:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for token in inline.findall(line):
                raw = token.rstrip("。，,.)")
                if any(char in raw for char in "*<>${}|"):
                    continue
                candidate = raw
                if ":" in raw:  # `path.py:symbol` 形式
                    head, _, tail = raw.partition(":")
                    if head.endswith(FILE_SUFFIXES) and tail:
                        candidate = head
                if not candidate.endswith(FILE_SUFFIXES):
                    continue
                # 只校验"含目录的相对路径"；裸文件名多指归档内部或生成物，不在此校验
                if "/" not in candidate:
                    continue
                if candidate.startswith(RUNTIME_PATH_PREFIXES):
                    continue
                if not Path(candidate).exists():
                    errors.append(f"{path}:{line_number} 引用了不存在的文件：`{candidate}`")


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
    check_discoverable(errors)
    check_numeric_contracts(errors)
    check_referenced_paths(doc_files, errors)

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
