"""死代码扫描器的行为测试：既要能命中零引用定义，也不能误报被引用项。"""

from __future__ import annotations

from pathlib import Path

from scripts.check_dead_symbols import find_dead_symbols, main


def make_repo(tmp_path: Path, module_body: str, caller_body: str = "") -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "scripts").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    (repo / "src" / "pkg" / "mod.py").write_text(module_body, encoding="utf-8")
    if caller_body:
        (repo / "scripts" / "caller.py").write_text(caller_body, encoding="utf-8")
    return repo


def test_flags_unused_constant_but_not_used_function(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        'UNUSED = {".sh"}\n\n\ndef used() -> int:\n    return 1\n',
        "from pkg.mod import used\n\nprint(used())\n",
    )

    dead = find_dead_symbols(repo)

    assert [item.name for item in dead] == ["UNUSED"]
    assert dead[0].label.startswith("src/pkg/mod.py:1")


def test_usage_in_docs_or_workflows_counts_as_reference(tmp_path: Path) -> None:
    """只要出现在仓库文本里就不算死代码（含文档与工作流）。"""
    repo = make_repo(tmp_path, 'CLI_FLAG = "--yes"\n')
    (repo / "docs" / "usage.md").write_text("使用 `CLI_FLAG` 打开\n", encoding="utf-8")

    assert find_dead_symbols(repo) == []


def test_allowed_names_are_skipped(tmp_path: Path) -> None:
    """外部入口这类已知假阳性要走 ALLOWED 显式登记，而不是放宽规则。"""
    repo = make_repo(tmp_path, "PROTOCOL_METHOD = 1\n")
    dead = find_dead_symbols(repo, allowed={"PROTOCOL_METHOD": "被宿主反射调用"})
    assert dead == []
    assert find_dead_symbols(repo) != []


def test_private_dunder_names_are_ignored(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "def __getattr__(name: str) -> None:\n    return None\n")
    assert find_dead_symbols(repo) == []


def test_cli_reports_failure_and_missing_roots(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "UNUSED = 1\n")
    assert main(["--repo", str(repo)]) == 1
    assert main(["--repo", str(tmp_path / "nope")]) == 2
