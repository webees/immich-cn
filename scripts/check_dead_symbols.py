"""扫描 ``src/`` 与 ``scripts/`` 里的零引用模块级定义。

「死代码与未使用配置」是固定的审计焦点，但此前每轮都要手写一遍扫描脚本：第 63/73/83
轮都命中同一个零引用常量 `SHELL_SUFFIXES`，直到第 262 轮才真正删除——因为没有可重复
执行的资产，结论无法对拍。本脚本把判定口径固定下来。

口径：模块级 ``def`` / ``async def`` / ``class`` 与大写常量；在仓库文本范围内（源码、
测试、工作流、Makefile、文档、CHANGELOG）搜索该名字，只有定义行出现即视为零引用。
已知假阳性（Protocol 方法、``__all__`` 导出、被外部字符串调用的入口）放进 ``ALLOWED``。

用法：

    python -m scripts.check_dead_symbols

退出码：``0`` 无零引用，``1`` 存在零引用，``2`` 路径或解析错误。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: 允许存在的零引用定义：名字 -> 原因。当前为空，命中即视为需要处理。
ALLOWED: dict[str, str] = {}


@dataclass(frozen=True, slots=True)
class DeadSymbol:
    path: str
    name: str
    line: int

    @property
    def label(self) -> str:
        return f"{self.path}:{self.line} {self.name}"


def _corpus_paths(repo: Path) -> list[Path]:
    patterns = (
        "src/**/*.py",
        "scripts/*.py",
        "tests/**/*.py",
        ".github/**/*.yml",
        ".github/*.md",
        "docs/*.md",
        "examples/**/*.yml",
        "Makefile",
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "pyproject.toml",
    )
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(sorted(repo.glob(pattern)))
    return [path for path in paths if path.is_file()]


def _module_definitions(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.append((node.name, node.lineno))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    found.append((target.id, node.lineno))
    return found


def find_dead_symbols(repo: Path, *, allowed: dict[str, str] | None = None) -> list[DeadSymbol]:
    """返回零引用的模块级定义（不含 ``ALLOWED`` 中的名字）。"""
    allow = ALLOWED if allowed is None else allowed
    corpus = {str(path): path.read_text(encoding="utf-8") for path in _corpus_paths(repo)}
    definition_files = [
        *sorted((repo / "src").rglob("*.py")),
        *sorted((repo / "scripts").glob("*.py")),
    ]
    dead: list[DeadSymbol] = []
    for path in sorted(definition_files):
        relative = str(path.relative_to(repo))
        for name, line in _module_definitions(path):
            if name.startswith("__") or name in allow:
                continue
            pattern = re.compile(rf"(?<![A-Za-z0-9_.]){re.escape(name)}(?![A-Za-z0-9_])")
            referenced = False
            for source, text in corpus.items():
                for number, raw in enumerate(text.splitlines(), start=1):
                    if source == str(path) and number == line:
                        continue
                    if pattern.search(raw):
                        referenced = True
                        break
                if referenced:
                    break
            if not referenced:
                dead.append(DeadSymbol(relative, name, line))
    return dead


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path())
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    if not (repo / "src").is_dir() or not (repo / "scripts").is_dir():
        print(f"::error::{repo} 下找不到 src/ 或 scripts/", file=sys.stderr)
        return 2
    try:
        dead = find_dead_symbols(repo)
    except (OSError, SyntaxError) as error:
        print(f"::error::扫描失败：{error}", file=sys.stderr)
        return 2

    for item in dead:
        print(f"[!!] 零引用模块级定义：{item.label}")
    if dead:
        print(f"死代码扫描失败：{len(dead)} 项（确认属于外部入口时写入 ALLOWED 并注明原因）")
        return 1
    if ALLOWED:
        print(f"死代码扫描通过：没有零引用定义，ALLOWED 中登记 {len(ALLOWED)} 个已知例外")
    else:
        print("死代码扫描通过：没有零引用定义")
    return 0


if __name__ == "__main__":
    sys.exit(main())
