"""为仓库自带的四个契约护栏补测试。

这些脚本此前只对"当前仓库状态"运行，没有任何用例验证它们**真的能失败**：
一旦某条规则失效（正则写错、路径变了），CI 依然全绿，保护会静默消失。
这里对每个护栏都构造"合格基线"与"已知坏输入"两组场景。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import scripts.check_artifacts as check_artifacts

REPO_ROOT = Path(__file__).resolve().parent.parent
#: 护栏运行所需的仓库子集（按脚本实际读取的内容）
REPO_SUBSET = (
    "src",
    "scripts",
    "docker",
    "docs",
    "examples",
    ".github",
    "config",
    "tests",
    "Makefile",
    "pyproject.toml",
    "README.md",
    "NOTICE",
    "CONTRIBUTING.md",
    "SECURITY.md",
)


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for name in REPO_SUBSET:
        source = REPO_ROOT / name
        target = root / name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copyfile(source, target)
    return root


def run_checker(root: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    """以 ``root`` 为工作目录运行**真实**护栏脚本（``root`` 可以是仓库副本或临时目录）。

    脚本本身取自当前仓库：被测试的是"真实实现 + 被篡改的输入"，
    而不是副本里的脚本，否则测试会随副本一起被改坏。
    """
    env = {**os.environ, "PYTHONPYCACHEPREFIX": str(root / ".pycache-probe")}
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script), *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def mutate(path: Path, old: str, new: str) -> None:
    """改写文件并断言改写确实落盘（否则实验无效）。"""
    text = path.read_text(encoding="utf-8")
    assert old in text, f"待替换内容不存在：{path}"
    mutated = text.replace(old, new, 1)
    assert mutated != text
    path.write_text(mutated, encoding="utf-8")
    assert new in path.read_text(encoding="utf-8"), "改写未落盘"


# --------------------------------------------------------------------------
# check_docs.py
# --------------------------------------------------------------------------


def test_check_docs_passes_on_repo_copy(repo_copy: Path) -> None:
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_docs_detects_undocumented_env_var(repo_copy: Path) -> None:
    target = repo_copy / "src" / "immich_cn" / "models.py"
    mutate(target, "GEO_COLUMNS = 19", 'GEO_COLUMNS = 19\nUNDOCUMENTED = "IMMICH_CN_UNDOCUMENTED_PROBE"')
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "IMMICH_CN_UNDOCUMENTED_PROBE" in result.stdout


def test_check_docs_detects_cli_flag_drift(repo_copy: Path) -> None:
    readme = repo_copy / "README.md"
    mutate(readme, "## 快速开始", "`immich-cn all --definitely-not-a-flag`\n\n## 快速开始")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "--definitely-not-a-flag" in result.stdout


def test_check_docs_detects_missing_notice_reference(repo_copy: Path) -> None:
    readme = repo_copy / "README.md"
    licensing = repo_copy / "docs" / "licensing.md"
    mutate(readme, "[NOTICE](NOTICE)", "NOTICE")
    mutate(licensing, "[NOTICE](../NOTICE)", "NOTICE")
    # 两处链接都被移除后，NOTICE 只在正文里作为普通词出现，不应再被算作引用
    for path in (readme, licensing):
        text = path.read_text(encoding="utf-8").replace("NOTICE", "许可说明")
        path.write_text(text, encoding="utf-8")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "NOTICE" in result.stdout


def test_check_docs_detects_numeric_drift(repo_copy: Path) -> None:
    readme = repo_copy / "README.md"
    mutate(readme, "共 14 个制品", "共 13 个制品")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "13 个制品" in result.stdout


def test_check_docs_detects_makefile_download_size_drift(repo_copy: Path) -> None:
    makefile = repo_copy / "Makefile"
    mutate(makefile, "首次下载约 260 MiB 压缩数据", "首次下载约 1.5 GiB 压缩数据")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "首次下载体积" in result.stdout or "压缩下载约 260 MiB" in result.stdout


def test_check_docs_detects_wrong_image_dataset_claim(repo_copy: Path) -> None:
    faq = repo_copy / "docs" / "faq.md"
    mutate(
        faq,
        "镜像内置的是默认非 full 数据集",
        "镜像内置的是 full 数据集（点位更多）\n\n镜像内置的是默认非 full 数据集",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "不能声称内置 full 数据集" in result.stdout


def test_check_docs_detects_missing_referenced_path(repo_copy: Path) -> None:
    """文档引用的仓库文件写错路径（例如漏掉 src/ 前缀）必须被报出。"""
    contributing = repo_copy / "CONTRIBUTING.md"
    mutate(
        contributing,
        "`src/immich_cn/providers/__init__.py:build_chain`",
        "`providers/__init__.py:build_chain`",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "引用了不存在的文件" in result.stdout


# --------------------------------------------------------------------------
# check_workflows.py
# --------------------------------------------------------------------------


def test_check_workflows_passes_on_repo_copy(repo_copy: Path) -> None:
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_workflows_detects_run_block_interpolation(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    mutate(workflow, '--patterns "$INPUT_PATTERNS"', '--patterns "${{ inputs.patterns }}"')
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "run 块直接插值" in result.stdout


def test_check_workflows_detects_unpinned_action(repo_copy: Path) -> None:
    """外部 Action 使用可重定向的 vN 标签时必须失败。"""
    workflow = repo_copy / ".github" / "workflows" / "ci.yml"
    mutate(
        workflow,
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7",
        "actions/checkout@v7",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "未固定到 40 位 commit SHA" in result.stdout


def test_check_workflows_detects_delete_then_recreate_release(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "update-data.yml"
    mutate(
        workflow,
        '            echo "上游数据与构建配置均无变化，已跳过发布与镜像推送。"',
        "            gh release delete auto-release --yes --cleanup-tag || true\n"
        "            gh release create auto-release dist/*\n"
        '            echo "上游数据与构建配置均无变化，已跳过发布与镜像推送。"',
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "先删除后重建" in result.stdout


def test_check_workflows_detects_release_metadata_before_assets(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "update-data.yml"
    mutate(
        workflow,
        '            echo "上游数据与构建配置均无变化，已跳过发布与镜像推送。"',
        "            gh release edit probe --title new\n"
        "            gh release upload probe dist/*\n"
        '            echo "上游数据与构建配置均无变化，已跳过发布与镜像推送。"',
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "替换资产前更新了元数据" in result.stdout


def test_check_workflows_detects_illegal_key_on_reusable_job(repo_copy: Path) -> None:
    """这次修复过的真实事故：reusable 调用 job 上出现 timeout-minutes。"""
    workflow = repo_copy / ".github" / "workflows" / "update-data.yml"
    mutate(
        workflow,
        "    uses: ./.github/workflows/_build-data.yml\n    secrets: inherit\n",
        "    uses: ./.github/workflows/_build-data.yml\n    secrets: inherit\n    timeout-minutes: 90\n",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "timeout-minutes" in result.stdout


def test_check_workflows_detects_dangling_step_reference(repo_copy: Path) -> None:
    """引用不存在的 step id 时表达式会静默为空，必须被静态拦下。"""
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    mutate(workflow, "steps.meta.outputs.date", "steps.nonexistent.outputs.date")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "不存在的 step id" in result.stdout


def test_check_workflows_detects_undeclared_reusable_output(repo_copy: Path) -> None:
    """引用被调用工作流未声明的 output 同样会静默为空。"""
    workflow = repo_copy / ".github" / "workflows" / "update-data.yml"
    mutate(workflow, "needs.build.outputs.changed", "needs.build.outputs.changed_typo")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "未声明的输出" in result.stdout


# --------------------------------------------------------------------------
# check_shell.py
# --------------------------------------------------------------------------


def test_check_shell_passes_on_repo_copy(repo_copy: Path) -> None:
    result = run_checker(repo_copy, "check_shell.py")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_shell_detects_cjk_adjacent_variable(repo_copy: Path) -> None:
    """这次修复过两次的真实事故：$VAR 紧跟全角字符被并入变量名。"""
    script = repo_copy / "docker" / "apply-pattern.sh"
    original = script.read_text(encoding="utf-8")
    script.write_text(original.rstrip("\n") + '\necho "结果：$pattern（测试）"\n', encoding="utf-8")
    result = run_checker(repo_copy, "check_shell.py")
    assert result.returncode == 1
    assert "$pattern" in result.stdout


# --------------------------------------------------------------------------
# check_artifacts.py
# --------------------------------------------------------------------------


def _make_dist(root: Path) -> Path:
    dist = root / "dist"
    dist.mkdir()
    lines = "\t".join(["1"] + ["x"] * 18) + "\n"
    for name in ("geodata.zip", "geodata_full.zip"):
        with zipfile.ZipFile(dist / name, "w") as archive:
            archive.writestr("geodata/cities500.txt", lines)
    with gzip.open(dist / "patterns.tsv.gz", "wt", encoding="utf-8") as handle:
        handle.write("geoname_id\t{admin_2}\n1\t测试\n")

    artifact = dist / "geodata.zip"
    extra = dist / "patterns.tsv.gz"
    variants = [
        {
            "file": artifact.name,
            "sizeBytes": artifact.stat().st_size,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        },
        {
            "file": extra.name,
            "sizeBytes": extra.stat().st_size,
            "sha256": hashlib.sha256(extra.read_bytes()).hexdigest(),
        },
    ]
    (dist / "manifest.json").write_text(
        json.dumps({"variants": variants}, ensure_ascii=False),
        encoding="utf-8",
    )
    (dist / "SHA256SUMS").write_text(
        "".join(f"{variant['sha256']}  {variant['file']}\n" for variant in variants),
        encoding="utf-8",
    )
    return dist


def test_check_artifacts_passes_on_minimal_dist(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    result = run_checker(tmp_path, "check_artifacts.py", str(dist))
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_artifacts_detects_tampered_zip(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    target = dist / "patterns.tsv.gz"  # 非 zip 制品：只有哈希层能发现
    original = target.read_bytes()
    # 同尺寸篡改：只翻转一个字节，确保"尺寸检查发现不了"
    middle = len(original) // 2
    tampered = bytearray(original)
    tampered[middle] ^= 0xFF
    target.write_bytes(bytes(tampered))
    assert target.stat().st_size == len(original)
    result = run_checker(tmp_path, "check_artifacts.py", str(dist))
    assert result.returncode == 1
    assert "patterns.tsv.gz" in result.stdout


def test_check_artifacts_manifest_hash_layer(tmp_path: Path) -> None:
    """直接验证 manifest 哈希层：把它削弱后本用例必须失败。"""
    dist = _make_dist(tmp_path)
    target = dist / "patterns.tsv.gz"
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0xFF
    target.write_bytes(bytes(data))
    errors: list[str] = []
    check_artifacts.check_manifest(dist, errors)
    assert any("patterns.tsv.gz" in error for error in errors), errors


def test_check_artifacts_checksums_layer(tmp_path: Path) -> None:
    """直接验证 SHA256SUMS 层：把它削弱后本用例必须失败。"""
    dist = _make_dist(tmp_path)
    target = dist / "patterns.tsv.gz"
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0xFF
    target.write_bytes(bytes(data))
    errors: list[str] = []
    check_artifacts.check_checksums(dist, errors)
    assert any("patterns.tsv.gz" in error for error in errors), errors


def test_check_artifacts_rejects_zip_path_traversal(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    with zipfile.ZipFile(dist / "geodata.zip", "a") as archive:
        archive.writestr("../escape.txt", "escape")

    errors: list[str] = []
    check_artifacts.check_zips(dist, errors)
    assert any("路径越界" in error for error in errors), errors


def test_check_artifacts_rejects_zip_symlink(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    with zipfile.ZipFile(dist / "geodata.zip", "a") as archive:
        info = zipfile.ZipInfo("geodata/link")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "../escape.txt")

    errors: list[str] = []
    check_artifacts.check_zips(dist, errors)
    assert any("符号链接" in error for error in errors), errors


def test_check_artifacts_reports_corrupt_zip_without_traceback(tmp_path: Path) -> None:
    """损坏的 zip 必须以校验错误呈现，而不是抛栈崩掉。"""
    dist = _make_dist(tmp_path)
    (dist / "geodata.zip").write_bytes(b"this is not a zip file")
    result = run_checker(tmp_path, "check_artifacts.py", str(dist))
    assert result.returncode == 1
    assert "无法作为 zip 读取" in result.stdout
    assert "Traceback" not in result.stderr
