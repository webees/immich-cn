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
import sqlite3
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
    "CITATION.cff",
    "LICENSE",
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
    target = repo_copy / "src" / "immich_cn" / "domain.py"
    mutate(target, "GEO_COLUMNS = 19", 'GEO_COLUMNS = 19\nUNDOCUMENTED = "IMMICH_CN_UNDOCUMENTED_PROBE"')
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "IMMICH_CN_UNDOCUMENTED_PROBE" in result.stdout


def test_check_docs_detects_env_default_drift(repo_copy: Path) -> None:
    """docs/development.md 把默认值写错时必须被报出。"""
    development = repo_copy / "docs" / "development.md"
    mutate(development, "| `IMMICH_CN_AMAP_QPS` | `3` |", "| `IMMICH_CN_AMAP_QPS` | `5` |")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "实现为" in result.stdout


def test_check_docs_detects_env_default_source_change(repo_copy: Path) -> None:
    """实现默认值变化但文档未同步时必须被报出。"""
    amap = repo_copy / "src" / "immich_cn" / "providers" / "amap.py"
    mutate(amap, 'positive_int_env("IMMICH_CN_AMAP_QPS", 3)', 'positive_int_env("IMMICH_CN_AMAP_QPS", 9)')
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "IMMICH_CN_AMAP_QPS" in result.stdout


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
    mutate(readme, "共 14 个 geodata variant", "共 13 个 geodata variant")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "13 个 geodata 变体" in result.stdout


def test_check_docs_detects_makefile_download_size_drift(repo_copy: Path) -> None:
    makefile = repo_copy / "Makefile"
    mutate(makefile, "首次下载约 260 MiB 压缩数据", "首次下载约 1.5 GiB 压缩数据")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "首次下载体积" in result.stdout or "压缩下载约 260 MiB" in result.stdout


def test_check_docs_requires_complete_make_check_description(repo_copy: Path) -> None:
    """make check 的说明不能漏掉 docs/workflows/shellcheck 门禁。"""
    contributing = repo_copy / "CONTRIBUTING.md"
    mutate(
        contributing,
        "make check       # lint + typecheck + test + docs + workflows + shellcheck",
        "make check       # lint + mypy + pytest",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "实际门禁" in result.stdout


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


def test_check_docs_detects_stale_plain_patterns_table_claim(repo_copy: Path) -> None:
    development = repo_copy / "docs" / "development.md"
    mutate(
        development,
        "明文变体表 `immich-cn-patterns-v1.tsv` 默认不会生成",
        "明文变体表 `immich-cn-patterns-v1.tsv` 默认在打包完成后删除",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "不生成明文 immich-cn-patterns-v1.tsv" in result.stdout


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


def test_check_docs_detects_undocumented_source(repo_copy: Path) -> None:
    """新增上游数据源但未同步 docs/data-sources.md 时必须被报出。"""
    settings = repo_copy / "src" / "immich_cn" / "settings.py"
    mutate(
        settings,
        '        SourceSpec(\n            name="alternateNamesV2",',
        "        SourceSpec(\n"
        '            name="probeUndocumentedSource",\n'
        '            url=f"{GEONAMES_BASE}/probe.txt",\n'
        '            filename="probe.txt",\n'
        "        ),\n"
        '        SourceSpec(\n            name="alternateNamesV2",',
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "未在 docs/data-sources.md 记录" in result.stdout


def test_check_docs_detects_stale_module_name(repo_copy: Path) -> None:
    """命名规范表里的现行模块名在源码中不存在时必须被报出。"""
    naming = repo_copy / "docs" / "naming-conventions.md"
    mutate(
        naming,
        "| `artifacts.py` | `artifact_spec.py` |",
        "| `artifacts.py` | `artifact_spec_v2.py` |",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "现行模块名" in result.stdout


def test_check_docs_detects_legacy_module_resurrection(repo_copy: Path) -> None:
    """命名规范表标记为旧名的模块重新出现时必须被报出。"""
    naming = repo_copy / "docs" / "naming-conventions.md"
    mutate(naming, "| `models.py` | `domain.py` |", "| `domain.py` | `domain.py` |")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "旧模块名" in result.stdout


def test_check_docs_detects_broken_markdown_link(repo_copy: Path) -> None:
    """Markdown 相对链接指向不存在的文件时必须被报出。"""
    readme = repo_copy / "README.md"
    mutate(readme, "- [许可与署名](docs/licensing.md)", "- [许可与署名](docs/licensing-x.md)")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "Markdown 链接目标不存在" in result.stdout


def test_check_docs_detects_manifest_field_drift(repo_copy: Path) -> None:
    """manifest 顶层字段名在文档里写错时必须被报出。"""
    spec = repo_copy / "docs" / "artifact-spec.md"
    mutate(spec, '"patternsTable": "immich-cn-patterns-tsv-v1.gz"', '"patternTableX": "immich-cn-patterns-tsv-v1.gz"')
    mutate(spec, "| `patternsTable` |", "| `patternTableX` |")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "未记录 manifest 顶层字段" in result.stdout


def test_check_docs_detects_new_manifest_field(repo_copy: Path) -> None:
    """实现新增 manifest 顶层字段但文档未记录时必须被报出。"""
    packaging = repo_copy / "src" / "immich_cn" / "packaging.py"
    mutate(
        packaging,
        'manifest["patternsTable"] = PATTERNS_FILE',
        'manifest["probeNewField"] = "x"\n    manifest["patternsTable"] = PATTERNS_FILE',
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "probeNewField" in result.stdout


def test_check_docs_requires_manifest_stats_scope(repo_copy: Path) -> None:
    """stats 是规范层 full 口径，缺少口径说明时必须被报出。"""
    spec = repo_copy / "docs" / "artifact-spec.md"
    mutate(spec, "`sourcePlaces + extraPlaces == outputPlaces`；", "记录数之间的关系见实现；")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "未说明 stats 口径" in result.stdout


def test_check_docs_requires_drop_split_documentation(repo_copy: Path) -> None:
    """丢弃计数必须分段说明，否则合并后的数字会被误读为单一阶段的丢弃量。"""
    spec = repo_copy / "docs" / "artifact-spec.md"
    mutate(spec, "`droppedPlaces = droppedCities + droppedExtra`：", "丢弃计数说明：")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "未说明 stats 口径" in result.stdout
    assert "droppedExtra" in result.stdout


def test_check_docs_detects_cjk_soft_break(repo_copy: Path) -> None:
    """中文段落被折行后，Markdown 会在渲染时插入空格，必须被拦下。"""
    readme = repo_copy / "README.md"
    mutate(readme, "本项目按独立实现组织：本仓库当前树中的代码", "本项目按独立实现组织：本仓库当前树中的\n代码")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "中文软换行" in result.stdout


def test_check_docs_detects_quote_soft_break(repo_copy: Path) -> None:
    """引用块内的软换行同样会插入空格。"""
    licensing = repo_copy / "docs" / "licensing.md"
    mutate(
        licensing,
        "属公有领域。数据处理由 immich-cn",
        "属公有领域。\n> 数据处理由 immich-cn",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "引用块内的中文软换行" in result.stdout


def test_check_docs_detects_citation_punct_space(repo_copy: Path) -> None:
    """CITATION.cff 折叠标量会在中文标点后留下空格，必须被拦下。"""
    citation = repo_copy / "CITATION.cff"
    mutate(
        citation,
        "为 Immich 提供中国本地化的 reverse geocoding geodata：核心",
        ("为 Immich 提供中国本地化的 reverse geocoding geodata： 核心"),
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "中文标点后出现空格" in result.stdout


def test_check_docs_detects_missing_hk_district(repo_copy: Path) -> None:
    """hk_districts 少一个区，该区地名就会丢掉「香港岛/九龙/新界」前缀。"""
    overrides = repo_copy / "config" / "overrides.toml"
    mutate(overrides, '"沙田区" = "新界"\n', "")
    # 生效表是「代码默认表 + 文件覆盖」的合并结果，因此两处都要移除才算真正缺失
    local = repo_copy / "src" / "immich_cn" / "localization.py"
    mutate(local, '    "沙田区": "新界",\n', "")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "沙田区" in result.stdout
    assert "香港区议会分区" in result.stdout


def test_check_docs_detects_wrong_hk_district_region(repo_copy: Path) -> None:
    """区域归属写错（例如把沙田划到九龙）同样要报错。"""
    overrides = repo_copy / "config" / "overrides.toml"
    mutate(overrides, '"沙田区" = "新界"', '"沙田区" = "九龙"')
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "区域归属与官方划分不符" in result.stdout


def test_check_docs_detects_language_priority_drift(repo_copy: Path) -> None:
    """文档里的中文语言优先级链必须与 LANGUAGE_PRIORITY 同序。"""
    doc = repo_copy / "docs" / "data-sources.md"
    mutate(doc, "zh-Hans > zh-CN >", "zh-CN > zh-Hans >")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "中文语言优先级与实现不一致" in result.stdout


def test_check_docs_rejects_stale_geodata_import_wording(repo_copy: Path) -> None:
    """上游是「相等则跳过」，写成「按新旧比较」必须被拦下。"""
    faq = repo_copy / "docs" / "faq.md"
    mutate(
        faq,
        "Immich 只在 `geodata-date.txt` 与上次导入时记录的值**不同**时才重新导入",
        "Immich 只在 `geodata-date.txt` 比上次导入时间更新时才重新导入",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "不准确的导入条件" in result.stdout


def test_check_docs_rejects_stale_geodata_import_wording_in_container_script(repo_copy: Path) -> None:
    """容器入口注释同样会指导维护者，不能绕过上游导入条件护栏。"""
    entrypoint = repo_copy / "docker" / "entrypoint.sh"
    mutate(
        entrypoint,
        "# Immich 只在 geodata-date.txt 与上次记录相等时跳过导入，这里给出显式刷新开关。",
        "# Immich 只在 geodata-date.txt 比上次导入更新时才重新导入，这里给出显式开关。",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "不准确的导入条件" in result.stdout


def test_check_docs_requires_explicit_immich_column_indexing(repo_copy: Path) -> None:
    """“第 1 列”在 0-based split 中会产生歧义，必须明确标注索引口径。"""
    architecture = repo_copy / "docs" / "architecture.md"
    mutate(
        architecture,
        "0-based column 1 是展示名",
        "第 1 列是展示名",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "0-based column" in result.stdout


def test_check_docs_rejects_ui_translation_as_upstream_requirement(repo_copy: Path) -> None:
    """Immich 已有 zh_Hans/zh_Hant，不能把 UI translation 写成需要上游修改。"""
    integration = repo_copy / "docs" / "immich-integration.md"
    mutate(
        integration,
        "| Upstream change required | 不在本项目做不安全 patch 或 UI fork | 全局 UI timezone、任意地图瓦片 |",
        "| Upstream change required | 不在本项目做不安全 patch 或 UI fork | 全局 UI timezone、任意地图瓦片、UI translation |",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "UI translation" in result.stdout


def test_check_docs_requires_current_release_locale_boundary(repo_copy: Path) -> None:
    """默认 release 线已内置中文 locale，文档不能只写 v3.3.0。"""
    integration = repo_copy / "docs" / "immich-integration.md"
    mutate(
        integration,
        "Immich 当前 `release` 线 v3.2.4 与 v3.3.0 都已内置",
        "Immich v3.3.0 已内置",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "v3.2.4" in result.stdout


def test_check_docs_requires_nginx_upload_buffering_contract(repo_copy: Path) -> None:
    """Nginx 示例漏掉上传旁路缓冲时，Immich 大文件会先被代理层落盘。"""
    nginx = repo_copy / "examples" / "nginx" / "immich-cn.conf"
    mutate(
        nginx,
        "    proxy_request_buffering off;\n",
        "",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "proxy_request_buffering off" in result.stdout


def test_check_docs_rejects_long_cache_on_nginx_errors(repo_copy: Path) -> None:
    """Cache-Control always 会把 404/500 也标成一年公共缓存。"""
    nginx = repo_copy / "examples" / "nginx" / "immich-cn.conf"
    mutate(
        nginx,
        'add_header Cache-Control "public, max-age=31536000, immutable";',
        'add_header Cache-Control "public, max-age=31536000, immutable" always;',
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "错误响应" in result.stdout


def test_check_docs_rejects_stale_immich_upload_path(repo_copy: Path) -> None:
    """Immich v3.3 媒体目录是 /data，旧示例不能继续挂载到 /usr/src/app/upload。"""
    compose = repo_copy / "examples" / "compose.server.yml"
    mutate(
        compose,
        "${UPLOAD_LOCATION}:/data",
        "${UPLOAD_LOCATION}:/usr/src/app/upload",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "/data" in result.stdout


def test_check_docs_requires_machine_learning_in_full_compose(repo_copy: Path) -> None:
    """完整 Compose 示例缺少 machine-learning 时功能会不完整。"""
    compose = repo_copy / "examples" / "compose.acceleration.yml"
    mutate(
        compose,
        "  immich-machine-learning:\n",
        "  immich-machine-learning-disabled:\n",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "immich-machine-learning" in result.stdout


def test_check_docs_requires_current_release_valkey_digest(repo_copy: Path) -> None:
    """默认 release 线当前为 v3.2.4，应使用对应官方 compose 的 Valkey digest。"""
    compose = repo_copy / "examples" / "compose.server.yml"
    mutate(
        compose,
        "sha256:70739f85ad2ee01a726a965584a0f94895f01b0c60b3cc8b0aeef11eaa6888cf",
        "sha256:c123e3715db63d06d4ad6964884037aa0d5d4d703939b9929954112889708e1d",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "Valkey" in result.stdout


def test_check_docs_rejects_stale_timezone_api_description(repo_copy: Path) -> None:
    """timezone 文档不能把 PUT 写成无条件批量更新方法。"""
    timezone = repo_copy / "docs" / "timezone.md"
    mutate(
        timezone,
        "并优先通过 `PATCH /api/assets` 批量更新；仅当旧版返回 `404`/`405` 时才回退到 `PUT /api/assets`",
        "并通过 `PUT /api/assets` 批量更新",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "PUT" in result.stdout


def test_check_docs_detects_license_field_drift(repo_copy: Path) -> None:
    """pyproject 的 license 与 LICENSE/CITATION 不一致时必须报错。"""
    pyproject = repo_copy / "pyproject.toml"
    mutate(pyproject, 'license = "MIT"', 'license = "Apache-2.0"')
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "许可声明不一致" in result.stdout
    assert "pyproject.toml 的 license" in result.stdout


def test_check_docs_detects_missing_data_license_exception(repo_copy: Path) -> None:
    """NOTICE 丢掉「数据制品不属于 MIT」的例外说明时必须报错。"""
    notice = repo_copy / "NOTICE"
    mutate(notice, "并不属于 MIT 许可范围", "属于 MIT 许可范围")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "数据制品不适用纯 MIT" in result.stdout


def test_check_docs_detects_version_drift(repo_copy: Path) -> None:
    """pyproject / __init__ / CITATION 三处版本号必须一致。"""
    citation = repo_copy / "CITATION.cff"
    mutate(citation, "version: 1.0.4", "version: 1.0.5")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "版本号不一致" in result.stdout


def test_check_docs_detects_package_version_drift(repo_copy: Path) -> None:
    """包的 __version__ 与 pyproject 漂移时同样要报错（镜像 OCI version 取自前者）。"""
    init = repo_copy / "src" / "immich_cn" / "__init__.py"
    mutate(init, '__version__ = "1.0.4"', '__version__ = "1.0.3"')
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "版本号不一致" in result.stdout


def test_check_docs_requires_i18n_asset_for_release_users(repo_copy: Path) -> None:
    """geodata zip 不含 langs/，让用户挂载它就必须同时说明要下载 i18n 覆盖包。"""
    deployment = repo_copy / "docs" / "deployment.md"
    mutate(
        deployment,
        "curl -fsSL -o immich-cn-i18n-json-v1.zip \\\n"
        "  https://github.com/webees/immich-cn/releases/latest/download/immich-cn-i18n-json-v1.zip\n",
        "",
    )
    mutate(deployment, "unzip -o immich-cn-i18n-json-v1.zip -d i18n-iso-countries", "true")

    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "immich-cn-i18n-json-v1.zip" in result.stdout


def test_check_docs_rejects_misleading_adm4_wording(repo_copy: Path) -> None:
    """把 73 条说成 GeoNames 的 ADM4 总数会被严重误读，必须拦下。"""
    readme = repo_copy / "README.md"
    mutate(
        readme,
        "拼不出第四级层级。",
        "拼不出第四级层级。因为 GeoNames 几乎没有乡镇级 `ADM4` 记录。",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "会被误读的 ADM4 表述" in result.stdout


def test_check_docs_requires_adm4_code_explanation(repo_copy: Path) -> None:
    """提到 73 条时必须说明那是「带 admin4 代码的数量」。"""
    readme = repo_copy / "README.md"
    mutate(readme, "带 `admin4` 代码的只有 73 条", "只有 73 条")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "未说明这是「带 admin4 代码的数量」" in result.stdout


def test_check_docs_rejects_stale_immich_countryinfo_boundary(repo_copy: Path) -> None:
    """Immich 的分界点是 3.3.0：写回 3.0 必须被拦下（上游 v3.0.0~v3.2.4 仍用 i18n-iso-countries）。"""
    readme = repo_copy / "README.md"
    mutate(readme, "3.3.0 起改读 countryInfo.txt", "3.0 起改读 countryInfo.txt")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "过时的 Immich 版本分界" in result.stdout


def test_check_docs_rejects_missing_countryinfo_boundary(repo_copy: Path) -> None:
    """提到 countryInfo.txt 却不写版本分界时同样要报错。"""
    readme = repo_copy / "README.md"
    mutate(readme, "（3.3.0 起改读 countryInfo.txt）", "（改读 countryInfo.txt）")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "未写明分界" in result.stdout or "没有任何文档声明" in result.stdout


def test_check_docs_detects_dataset_member_drift(repo_copy: Path) -> None:
    """归档成员名写成构建期中间文件名（dataset.sqlite）时必须报错。"""
    spec = repo_copy / "docs" / "data-format.md"
    mutate(spec, "| `immich-cn-dataset-v1.sqlite` |", "| `dataset.sqlite` |")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "数据集归档成员" in result.stdout


def test_check_docs_detects_sqlite_example_member_drift(repo_copy: Path) -> None:
    """sqlite3 示例必须使用归档内的真实成员名。"""
    spec = repo_copy / "docs" / "data-format.md"
    mutate(spec, "sqlite3 immich-cn-dataset-v1.sqlite \\", "sqlite3 dataset.sqlite \\")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "sqlite3 示例" in result.stdout


def test_check_docs_covers_release_notes_and_issue_template(repo_copy: Path) -> None:
    """Release 说明与 Issue 模板同样会被渲染，必须纳入资产名与换行护栏。"""
    note = repo_copy / ".github" / "auto_release_note.md"
    mutate(note, "`immich-cn-geodata-admin2-default-v1.zip`", "`immich-cn-geodata-immich-admin2-default-v1.zip`")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "重复项目命名空间" in result.stdout


def test_check_docs_covers_issue_template_soft_break(repo_copy: Path) -> None:
    """Issue 模板里的中文软换行会被渲染成空格，必须被拦下。"""
    template = repo_copy / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml"
    mutate(
        template,
        "固有限制：可以尝试 `immich-cn-geodata-admin2-full-v1.zip`，或到",
        "固有限制：可以尝试 `immich-cn-geodata-admin2-full-v1.zip`，\n        > 或到",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "中文软换行" in result.stdout


def test_check_docs_rejects_rewrite_positioning(repo_copy: Path) -> None:
    readme = repo_copy / "README.md"
    mutate(readme, "本项目按独立实现组织", "本项目是独立重写版本")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "错误的项目定位" in result.stdout


def test_check_docs_requires_china_localization_anchor(repo_copy: Path) -> None:
    """README 丢掉 canonical positioning 时必须失败，避免范围再次漂移。"""
    readme = repo_copy / "README.md"
    mutate(readme, "immich-cn 为 Immich 提供中国本地化的 reverse geocoding geodata", "Immich 数据工具")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "中国本地化定位锚点" in result.stdout


def test_check_docs_requires_china_localization_areas(repo_copy: Path) -> None:
    """core/optional scope 表被删掉一项时必须失败，避免路线图只剩宣传性描述。"""
    localization = repo_copy / "docs" / "china-localization.md"
    mutate(localization, "| 检索 |", "| 查询 |")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "缺少「检索」行" in result.stdout


def test_check_docs_requires_project_scope_sections(repo_copy: Path) -> None:
    """canonical scope 必须显式区分 core、optional 和 non-goals。"""
    scope = repo_copy / "docs" / "project-scope.md"
    mutate(scope, "## Optional support", "## Other")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "Optional support" in result.stdout


def test_check_docs_rejects_deprecated_scope_phrases(repo_copy: Path) -> None:
    """已废弃的泛化定位不能重新写回 README。"""
    readme = repo_copy / "README.md"
    mutate(readme, "## 快速开始", "本地化不止于翻译：六个层面。\n\n## 快速开始")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "已废弃的范围表述" in result.stdout


def test_check_docs_requires_china_timezone(repo_copy: Path) -> None:
    """面向中国用户的部署示例必须显式设置中国时区。"""
    compose = repo_copy / "examples" / "compose.server.yml"
    mutate(compose, "      TZ: Asia/Shanghai\n", "")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "中国本地化默认时区" in result.stdout


def test_check_docs_requires_china_acceleration_entrypoint(repo_copy: Path) -> None:
    """README 必须把 CDN 与静态资源加速列为中国本地化的一等能力。"""
    readme = repo_copy / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "docs/china-acceleration.md" in text
    readme.write_text(text.replace("docs/china-acceleration.md", "docs/china-localization.md"), encoding="utf-8")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "docs/china-acceleration.md" in result.stdout


def test_check_docs_requires_acceleration_cache_boundary(repo_copy: Path) -> None:
    """加速文档必须明确不可变静态资源与 API 的缓存边界。"""
    acceleration = repo_copy / "docs" / "china-acceleration.md"
    text = acceleration.read_text(encoding="utf-8")
    assert "/_app/immutable/" in text
    acceleration.write_text(text.replace("/_app/immutable/", "/assets/"), encoding="utf-8")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "/_app/immutable/" in result.stdout


def test_check_docs_requires_acceleration_examples(repo_copy: Path) -> None:
    """加速文档必须引用可直接部署的 compose 与 Nginx 示例。"""
    acceleration = repo_copy / "docs" / "china-acceleration.md"
    mutate(acceleration, "../examples/compose.acceleration.yml", "../examples/compose.server.yml")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "../examples/compose.acceleration.yml" in result.stdout


def test_check_docs_requires_jsdelivr_release_limit(repo_copy: Path) -> None:
    """免费 CDN 说明必须保留 Release 附件不能被 jsDelivr 直接代理的边界。"""
    acceleration = repo_copy / "docs" / "china-acceleration.md"
    mutate(acceleration, "Release 资产", "Release 文件")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "Release 资产" in result.stdout


def test_check_docs_requires_china_jsdelivr_default(repo_copy: Path) -> None:
    """加速文档必须保留中国默认节点和用户可配置入口。"""
    acceleration = repo_copy / "docs" / "china-acceleration.md"
    text = acceleration.read_text(encoding="utf-8")
    assert "cdn.jsdmirror.com" in text
    acceleration.write_text(text.replace("cdn.jsdmirror.com", "cdn.jsdelivr.net"), encoding="utf-8")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "cdn.jsdmirror.com" in result.stdout


def test_check_docs_requires_english_data_update_badge(repo_copy: Path) -> None:
    """GitHub badge alt text 过长会溢出，必须使用英文短标签。"""
    readme = repo_copy / "README.md"
    mutate(readme, "[![Data Update]", "[![全自动更新数据]")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "badge" in result.stdout


def test_check_docs_requires_ghcr_mirror_default(repo_copy: Path) -> None:
    """中国部署文档必须默认使用可达 GHCR mirror。"""
    readme = repo_copy / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "ghcr.nju.edu.cn" in text
    readme.write_text(text.replace("ghcr.nju.edu.cn", "ghcr.io"), encoding="utf-8")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "ghcr.nju.edu.cn" in result.stdout


def test_check_docs_requires_ghcr_mirror_override(repo_copy: Path) -> None:
    """Compose 示例必须允许用户切换到官方或其他 mirror。"""
    compose = repo_copy / "examples" / "compose.server.yml"
    text = compose.read_text(encoding="utf-8")
    assert "IMMICH_CN_GHCR_MIRROR" in text
    compose.write_text(text.replace("IMMICH_CN_GHCR_MIRROR", "REMOVED_GHCR_MIRROR"), encoding="utf-8")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "IMMICH_CN_GHCR_MIRROR" in result.stdout


def test_check_docs_requires_immich_integration_contract(repo_copy: Path) -> None:
    """Immich 上游依赖和不可修改边界必须有契约文档。"""
    doc = repo_copy / "docs" / "immich-integration.md"
    mutate(doc, "Upstream change required", "Other change")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "Upstream change required" in result.stdout


def test_check_docs_requires_technical_terminology(repo_copy: Path) -> None:
    """术语规范必须保留英文核心技术术语，防止文档重新退化为一味中文化。"""
    terminology = repo_copy / "docs" / "terminology.md"
    mutate(terminology, "| `artifact` |", "| `制品` |")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "artifact" in result.stdout


def test_check_docs_rejects_process_claims(repo_copy: Path) -> None:
    """历史过程断言（例如“未从同类项目移植”）无法由当前树验证，必须被拒绝。"""
    readme = repo_copy / "README.md"
    mutate(readme, "本项目按独立实现组织", "本项目按独立实现组织，也未从同类项目移植实现")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "不可验证或越界声明" in result.stdout


def test_check_docs_rejects_legal_conclusions(repo_copy: Path) -> None:
    """工程文档不能对法律状态下结论，例如“不构成格式继承”。"""
    licensing = repo_copy / "docs" / "licensing.md"
    mutate(licensing, "本项目按独立实现组织", "本项目按独立实现组织，不构成任何格式继承")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "不可验证或越界声明" in result.stdout


def test_check_docs_requires_independence_guidance(repo_copy: Path) -> None:
    """独立性声明必须指向可核查的范围与边界，否则读者无法判断声明依据。"""
    readme = repo_copy / "README.md"
    mutate(
        readme,
        "核查范围、关键词与边界见 [docs/documentation-policy.md](docs/documentation-policy.md)。",
        "核查范围、关键词与边界见项目维护记录。",
    )
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "核查范围与边界" in result.stdout


def test_check_docs_rejects_sla_promise(repo_copy: Path) -> None:
    """响应时间无法保证，必须写成“通常”并注明不是服务水平承诺。"""
    security = repo_copy / "SECURITY.md"
    mutate(security, "我们通常会在 7 天内给出初步回复", "我们会在 7 天内给出初步回复")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "时间承诺" in result.stdout


def test_check_docs_requires_upstream_acknowledgement_at_bottom(repo_copy: Path) -> None:
    readme = repo_copy / "README.md"
    link = (
        "- [ZingLix/immich-geodata-cn](https://github.com/ZingLix/immich-geodata-cn)："
        "早期中文 Immich geodata 思路提供了启发；本项目按独立实现组织，"
        "当前树未引用或打包该项目的代码与人工整理数据（核查方式见 [文档严谨性规范](docs/documentation-policy.md)）。"
    )
    mutated = readme.read_text(encoding="utf-8").replace(link, "")
    mutated = mutated.replace("## 数据模型与使用方式", f"{link}\n\n## 数据模型与使用方式")
    readme.write_text(mutated, encoding="utf-8")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "底部致谢" in result.stdout


def test_check_docs_rejects_absolute_claims(repo_copy: Path) -> None:
    readme = repo_copy / "README.md"
    mutate(readme, "本项目按独立实现组织", "本项目是完全独立的实现")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "绝对化表述" in result.stdout


def test_check_docs_rejects_legacy_asset_names(repo_copy: Path) -> None:
    readme = repo_copy / "README.md"
    mutate(readme, "## 快速开始", "`immich-cn-geodata-immich-admin2-default-v1.zip`\n\n## 快速开始")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "重复项目命名空间" in result.stdout


def test_check_docs_rejects_unregistered_asset_names(repo_copy: Path) -> None:
    readme = repo_copy / "README.md"
    mutate(readme, "## 快速开始", "`immich-cn-random-asset-v1.zip`\n\n## 快速开始")
    result = run_checker(repo_copy, "check_docs.py")
    assert result.returncode == 1
    assert "未登记的发布资产名" in result.stdout


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


def test_check_workflows_detects_top_level_write_permissions(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "update-data.yml"
    mutate(
        workflow,
        "permissions:\n  contents: read\n\nenv:",
        "permissions:\n  contents: write\n\nenv:",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "顶层 permissions 含 write" in result.stdout


def test_check_workflows_detects_delete_then_recreate_release(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "update-data.yml"
    mutate(
        workflow,
        '            echo "上游数据、构建配置与发布器修订均无变化，已跳过发布与镜像推送。"',
        "            gh release delete auto-release --yes --cleanup-tag || true\n"
        "            gh release create auto-release dist/*\n"
        '            echo "上游数据、构建配置与发布器修订均无变化，已跳过发布与镜像推送。"',
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "先删除后重建" in result.stdout


def test_check_workflows_detects_release_metadata_before_assets(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "update-data.yml"
    mutate(
        workflow,
        '            echo "上游数据、构建配置与发布器修订均无变化，已跳过发布与镜像推送。"',
        "            gh release edit probe --title new\n"
        "            gh release upload probe dist/*\n"
        '            echo "上游数据、构建配置与发布器修订均无变化，已跳过发布与镜像推送。"',
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "替换资产前更新了元数据" in result.stdout


def test_check_workflows_requires_release_asset_reconciliation(repo_copy: Path) -> None:
    """滚动 Release 清理后必须验证 dist 与 Release 资产完全一致。"""
    workflow = repo_copy / ".github" / "workflows" / "update-data.yml"
    mutate(
        workflow,
        "python scripts/cleanup.py --verify-release-assets auto-release --dist-dir dist",
        "true",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "post-cleanup verification" in result.stdout


def test_check_workflows_rejects_immutable_snapshot_regression(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "update-data.yml"
    mutate(
        workflow,
        '            revision_tag="data-${DATE}-sha-${short_sha}"',
        '            revision_tag="data-${DATE}"',
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "未创建 data-DATE-sha-短提交" in result.stdout


def test_check_workflows_requires_image_supply_chain(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    mutate(
        workflow,
        '          cosign sign --yes "ghcr.io/${GITHUB_REPOSITORY}@${DATA_DIGEST}"\n'
        '          cosign sign --yes "ghcr.io/${GITHUB_REPOSITORY}-server@${SERVER_DIGEST}"',
        '          echo "skip cosign"',
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "缺少数据或 server 镜像的 Cosign keyless 签名" in result.stdout


def test_check_workflows_requires_cosign_verification(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    mutate(workflow, "cosign verify", "true")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "Cosign verification" in result.stdout


def test_check_workflows_requires_server_base_digest(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    mutate(workflow, "IMMICH_BASE_DIGEST=@${BASE_DIGEST}", "IMMICH_BASE_DIGEST=")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "base digest" in result.stdout


def test_check_workflows_requires_base_digest_in_change_detection(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "previous_base_digest" in text
    workflow.write_text(text.replace("previous_base_digest", "previous_base"), encoding="utf-8")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "重建判断" in result.stdout


def test_check_workflows_requires_data_image_in_change_detection(repo_copy: Path) -> None:
    """data image 缺失时不能因 fingerprint 未变而跳过重建。"""
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "previous_data_digest" in text
    workflow.write_text(text.replace("previous_data_digest", "previous_data"), encoding="utf-8")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "data image 存在性" in result.stdout


def test_check_workflows_requires_release_assets_in_change_detection(repo_copy: Path) -> None:
    """Release 资产缺失或多出时不能因 fingerprint 未变而跳过发布。"""
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "release_assets_ok" in text
    workflow.write_text(text.replace("release_assets_ok", "release_assets"), encoding="utf-8")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "Release asset 集合" in result.stdout


def test_check_workflows_requires_snapshot_in_change_detection(repo_copy: Path) -> None:
    """最新 data-* 快照缺失或 fingerprint 不一致时不能跳过发布。"""
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "snapshot_ok" in text
    workflow.write_text(text.replace("snapshot_ok", "snapshot_check"), encoding="utf-8")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "不可变快照" in result.stdout


def test_check_workflows_requires_full_stack_smoke(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    mutate(
        workflow,
        '            if grep -q "Geodata import completed" server-smoke.log; then',
        "            if true; then",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "缺少 PostgreSQL/Redis/Immich 完整服务栈导入冒烟" in result.stdout


def test_check_workflows_requires_database_import_probe(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "SELECT count(*) FROM geodata_places" in text
    workflow.write_text(text.replace("SELECT count(*) FROM geodata_places", "SELECT 1"), encoding="utf-8")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "geodata_places" in result.stdout


def test_check_workflows_requires_api_config_probe(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    mutate(workflow, "/api/server/config", "/api/server/version")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "API/config" in result.stdout


def test_check_workflows_requires_distinct_oci_version_and_data_date(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    mutate(workflow, "org.immich-cn.data-date", "org.immich-cn.unlabeled-date")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "OCI version 未使用项目版本" in result.stdout


def test_check_workflows_requires_versioned_image_tag(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "release.yml"
    mutate(workflow, "      image-version: ${{ inputs.version }}", '      image-version: ""')
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "未把 Release 版本传递给镜像构建" in result.stdout


def test_check_workflows_requires_project_version_consistency(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "release.yml"
    mutate(workflow, "repo_version=", "unchecked_version=")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "缺少输入版本与 pyproject.toml 的一致性检查" in result.stdout


def test_check_workflows_requires_versioned_release_images(repo_copy: Path) -> None:
    """版本化 Release 不能关闭 image push，否则不会产生对应 package tag。"""
    workflow = repo_copy / ".github" / "workflows" / "release.yml"
    mutate(
        workflow,
        "          PUSH_IMAGES: ${{ inputs.push-images }}\n",
        "",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "image version tag" in result.stdout


def test_check_workflows_requires_post_build_versioned_image_tags(repo_copy: Path) -> None:
    """创建 GitHub Release 前必须验证构建产出的两个 image version tag。"""
    workflow = repo_copy / ".github" / "workflows" / "release.yml"
    mutate(
        workflow,
        "      - name: 验证 semantic version image tags\n",
        "      - name: disabled verification\n",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "创建 Release 前未验证" in result.stdout


def test_check_workflows_requires_version_tag_digest_match(repo_copy: Path) -> None:
    """version tag 指向的 digest 必须与本次 build 输出一致。"""
    workflow = repo_copy / ".github" / "workflows" / "release.yml"
    mutate(
        workflow,
        'test "$actual_server_digest" = "$EXPECTED_SERVER_DIGEST"\n',
        'test -n "$EXPECTED_SERVER_DIGEST"\n',
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "digest" in result.stdout


def test_check_workflows_rejects_vacuous_versioned_release_image_guard(repo_copy: Path) -> None:
    """保留 push-images 文案但把拒绝条件改成恒假时，护栏必须失败。"""
    workflow = repo_copy / ".github" / "workflows" / "release.yml"
    mutate(
        workflow,
        'if [ "$PUSH_IMAGES" != "true" ]; then',
        "if false; then",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "未实际拒绝 push-images=false" in result.stdout


def test_check_workflows_requires_release_preflight_checkout(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "release.yml"
    mutate(
        workflow,
        "  validate:\n"
        "    name: 检查版本可用性\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 10\n"
        "    permissions:\n"
        "      contents: read\n"
        "    steps:\n"
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7\n"
        "        with:\n"
        "          persist-credentials: false\n",
        "  validate:\n"
        "    name: 检查版本可用性\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 10\n"
        "    permissions:\n"
        "      contents: read\n"
        "    steps:\n",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "validate 缺少 checkout" in result.stdout


def test_check_workflows_requires_cleanup_apply_policy(repo_copy: Path) -> None:
    workflow = repo_copy / ".github" / "workflows" / "cleanup.yml"
    mutate(
        workflow,
        "          APPLY: ${{ github.event_name == 'schedule' || inputs.apply }}",
        "          APPLY: false",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "定时任务没有自动切换为 apply" in result.stdout


def test_check_workflows_requires_cleanup_failure_notifier(repo_copy: Path) -> None:
    """清理工作流失败时必须创建告警，不能只把失败留在 Actions 历史里。"""
    workflow = repo_copy / ".github" / "workflows" / "cleanup.yml"
    mutate(
        workflow,
        "  notify-failure:\n    name: Notify Failure\n    needs: [cleanup, resolve-previous-failure]\n    if: failure()\n",
        "  notify-failure:\n    name: Notify Failure\n    needs: [cleanup, resolve-previous-failure]\n    if: false()\n",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "缺少 cleanup 失败告警 job" in result.stdout


def test_check_workflows_requires_cleanup_notifier_issue_permission(repo_copy: Path) -> None:
    """缺少 issues: write 时告警步骤会失败，护栏必须直接拦下。"""
    workflow = repo_copy / ".github" / "workflows" / "cleanup.yml"
    mutate(
        workflow,
        "  notify-failure:\n"
        "    name: Notify Failure\n"
        "    needs: [cleanup, resolve-previous-failure]\n"
        "    if: failure()\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 10\n"
        "    permissions:\n"
        "      contents: read\n"
        "      issues: write\n",
        "  notify-failure:\n"
        "    name: Notify Failure\n"
        "    needs: [cleanup, resolve-previous-failure]\n"
        "    if: failure()\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 10\n"
        "    permissions:\n"
        "      contents: read\n",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "缺少 issues: write" in result.stdout


def test_check_workflows_detects_unscoped_cleanup_issue_search(repo_copy: Path) -> None:
    """清理告警搜索漏掉 automation 标签时可能误关用户 issue。"""
    workflow = repo_copy / ".github" / "workflows" / "cleanup.yml"
    mutate(
        workflow,
        "            --label automation --search '自动清理失败 in:title' \\\n",
        "            --search '自动清理失败 in:title' \\\n",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "未限定 automation 标签" in result.stdout


def test_check_workflows_detects_unscoped_automation_issue_search(repo_copy: Path) -> None:
    """自动化告警搜索必须限定 automation 标签，防止误关用户 issue。"""
    workflow = repo_copy / ".github" / "workflows" / "update-data.yml"
    mutate(
        workflow,
        '          number="$(gh issue list --repo "$GITHUB_REPOSITORY" --state open \\\n'
        "            --label automation \\\n"
        "            --search '自动更新数据失败 in:title' \\\n",
        '          number="$(gh issue list --repo "$GITHUB_REPOSITORY" --state open \\\n'
        "            --search '自动更新数据失败 in:title' \\\n",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "未限定 automation 标签" in result.stdout


def test_check_workflows_detects_incomplete_failure_notifier(repo_copy: Path) -> None:
    """失败通知必须覆盖 no-change 与告警收敛 job，否则它们失败时静默无告警。"""
    workflow = repo_copy / ".github" / "workflows" / "update-data.yml"
    mutate(
        workflow,
        "  notify-failure:\n    name: Notify Failure\n    needs: [build, release, no-change, resolve-previous-failure]\n",
        "  notify-failure:\n    name: Notify Failure\n    needs: [build, release, no-change]\n",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "notify-failure 的 needs 未覆盖" in result.stdout


def test_check_workflows_requires_published_url_verification(repo_copy: Path) -> None:
    """发布流程必须自检文档承诺的固定下载地址。"""
    workflow = repo_copy / ".github" / "workflows" / "update-data.yml"
    mutate(
        workflow,
        '/releases/latest/download/immich-cn-geodata-admin2-default-v1.zip"',
        '/releases/download/auto-release/immich-cn-geodata-admin2-default-v1.zip"',
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "固定下载地址" in result.stdout


def test_check_workflows_requires_compose_example_validation(repo_copy: Path) -> None:
    """CI 必须用 docker compose config 校验 examples/，否则文档示例会悄悄失效。"""
    workflow = repo_copy / ".github" / "workflows" / "ci.yml"
    mutate(workflow, 'docker compose -f "$file" config >/dev/null', "true")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "docker compose config" in result.stdout


def test_check_workflows_requires_all_compose_examples(repo_copy: Path) -> None:
    """新增 compose 示例后，CI 不能只校验旧的固定文件列表。"""
    workflow = repo_copy / ".github" / "workflows" / "ci.yml"
    mutate(
        workflow,
        'cp examples/compose.*.yml "$workdir/"',
        'cp examples/compose.server.yml examples/compose.volume.yml "$workdir/"',
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "通配符覆盖全部 compose 示例" in result.stdout


def test_check_workflows_requires_nginx_config_validation(repo_copy: Path) -> None:
    """Nginx 加速配置必须经过真实语法检查，不能只检查 YAML 挂载路径。"""
    workflow = repo_copy / ".github" / "workflows" / "ci.yml"
    mutate(workflow, "nginx -t", "nginx -T")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "nginx -t" in result.stdout


def test_check_workflows_requires_image_size_budget(repo_copy: Path) -> None:
    """CI 必须保留镜像尺寸预算，避免重新引入整包语言文件或额外包层。"""
    workflow = repo_copy / ".github" / "workflows" / "ci.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "IMAGE_SIZE_BUDGET_BYTES" in text
    workflow.write_text(text.replace("IMAGE_SIZE_BUDGET_BYTES", "REMOVED_SIZE_BUDGET"), encoding="utf-8")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "镜像尺寸" in result.stdout or "语言包最小化" in result.stdout


def test_check_workflows_requires_china_timezone(repo_copy: Path) -> None:
    """工作流不能继续依赖 runner 的 UTC 生成中国用户可见日期。"""
    workflow = repo_copy / ".github" / "workflows" / "ci.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "TZ: Asia/Shanghai" in text
    workflow.write_text(text.replace("TZ: Asia/Shanghai", "TZ: UTC"), encoding="utf-8")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "TZ: Asia/Shanghai" in result.stdout


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


def test_check_workflows_detects_missing_hash_files_path(repo_copy: Path) -> None:
    """hashFiles 指向不存在的路径时该维度静默为空，必须被静态拦下。"""
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    mutate(workflow, "hashFiles('src/immich_cn/settings.py')", "hashFiles('src/immich_cn/config.py')")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "hashFiles 引用了不存在的路径" in result.stdout


def test_check_workflows_allows_hash_files_globs(repo_copy: Path) -> None:
    """glob 形式的 hashFiles 参数不要求字面路径存在，避免误报。"""
    workflow = repo_copy / ".github" / "workflows" / "_build-data.yml"
    mutate(
        workflow,
        "hashFiles('src/immich_cn/settings.py')",
        "hashFiles('src/immich_cn/*.py')",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 0, result.stdout


def test_check_workflows_requires_checkout_credential_isolation(repo_copy: Path) -> None:
    """checkout 默认把 token 写进 .git/config，缺少 persist-credentials: false 必须被拦下。"""
    workflow = repo_copy / ".github" / "workflows" / "cleanup.yml"
    mutate(
        workflow,
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7\n"
        "        with:\n"
        "          persist-credentials: false\n",
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7\n",
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "persist-credentials" in result.stdout


def test_check_workflows_rejects_vacuous_checkout_guard(repo_copy: Path) -> None:
    """全部 checkout 步骤消失时必须报错，避免护栏静默失效。"""
    pattern = (
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7\n"
        "        with:\n"
        "          persist-credentials: false\n"
    )
    removed = 0
    for workflow in sorted((repo_copy / ".github" / "workflows").glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        if pattern not in text:
            continue
        removed += text.count(pattern)
        workflow.write_text(text.replace(pattern, ""), encoding="utf-8")
    assert removed > 0, "实验前提：仓库中应存在 checkout 步骤"
    remaining = [
        path
        for path in sorted((repo_copy / ".github" / "workflows").glob("*.yml"))
        if "actions/checkout@" in path.read_text(encoding="utf-8")
    ]
    assert not remaining, f"实验前提：checkout 应被全部移除，仍剩 {remaining}"
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "凭据持久化护栏可能已失效" in result.stdout


def test_check_workflows_detects_unknown_required_check(repo_copy: Path) -> None:
    """CONTRIBUTING 声明的 required check 必须真的有 job 会产生。"""
    contributing = repo_copy / "CONTRIBUTING.md"
    mutate(contributing, "`静态检查与单元测试 (Python 3.11)`", "`静态检查与单元测试 (Python 3.10)`")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "没有任何工作流 job 会产生" in result.stdout


def test_check_workflows_detects_required_check_matrix_drift(repo_copy: Path) -> None:
    """matrix 值变化会让 required check 名消失，护栏必须展开模板而不是比对字面量。"""
    workflow = repo_copy / ".github" / "workflows" / "ci.yml"
    mutate(
        workflow,
        'python-version: ["3.11", "3.12", "3.13"]',
        'python-version: ["3.10", "3.12", "3.13"]',
    )
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "Python 3.11" in result.stdout


def test_check_workflows_detects_duplicate_required_check(repo_copy: Path) -> None:
    """同名 job 由第二个工作流产生时存在混淆风险，必须报出。"""
    workflow = repo_copy / ".github" / "workflows" / "cleanup.yml"
    mutate(workflow, "    name: 清理 Release / Actions / GHCR\n", "    name: Docker 冒烟构建\n")
    result = run_checker(repo_copy, "check_workflows.py")
    assert result.returncode == 1
    assert "同名混淆风险" in result.stdout


# --------------------------------------------------------------------------
# check_shell.py
# --------------------------------------------------------------------------


def test_check_shell_passes_on_repo_copy(repo_copy: Path) -> None:
    result = run_checker(repo_copy, "check_shell.py")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_shell_requires_flag_documentation(repo_copy: Path) -> None:
    """实现了 CLI 参数却没在文件注释里说明时必须报错。"""
    script = repo_copy / "docker" / "install.sh"
    mutate(
        script,
        '    --geodata-only) langs_root=""; shift ;;',
        '    --probe-flag) langs_root=""; shift ;;\n    --geodata-only) langs_root=""; shift ;;',
    )
    result = run_checker(repo_copy, "check_shell.py")
    assert result.returncode == 1
    assert "--probe-flag" in result.stdout


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
    geodata_default = dist / "immich-cn-geodata-admin2-default-v1.zip"
    geodata_full = dist / "immich-cn-geodata-admin2-full-v1.zip"
    for name in (geodata_default.name, geodata_full.name):
        with zipfile.ZipFile(dist / name, "w") as archive:
            archive.writestr("geodata/cities500.txt", lines)
            archive.writestr("geodata/NOTICE.txt", "GeoNames CC BY 4.0\n")
    patterns = dist / "immich-cn-patterns-tsv-v1.gz"
    with gzip.open(patterns, "wt", encoding="utf-8") as handle:
        handle.write("geoname_id\t{admin_2}\n1\t测试\n")
    i18n = dist / "immich-cn-i18n-json-v1.zip"
    with zipfile.ZipFile(i18n, "w") as archive:
        archive.writestr("LICENSE", "MIT License\nCopyright\n")

    database = dist / "_dataset.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE dataset_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE sources (name TEXT PRIMARY KEY, url TEXT, sha256 TEXT, size_bytes INTEGER);
            CREATE TABLE countries (code TEXT PRIMARY KEY, name TEXT, iso3 TEXT, iso_numeric TEXT, geoname_id INTEGER);
            CREATE TABLE admin_areas (level INTEGER, code TEXT, name TEXT, PRIMARY KEY (level, code));
            CREATE TABLE places (geoname_id INTEGER PRIMARY KEY);
            CREATE TABLE place_names (geoname_id INTEGER PRIMARY KEY REFERENCES places(geoname_id));
            INSERT INTO dataset_meta(key, value) VALUES
                ('format', 'immich-cn.dataset/1'),
                ('schemaVersion', '1');
            INSERT INTO places(geoname_id) VALUES (1);
            INSERT INTO place_names(geoname_id) VALUES (1);
            """
        )
        connection.commit()
    finally:
        connection.close()
    dataset = dist / "immich-cn-dataset-sqlite-v1.zip"
    with zipfile.ZipFile(dataset, "w") as archive:
        archive.write(database, "immich-cn-dataset-v1.sqlite")
        archive.writestr(
            "schema.json",
            json.dumps({"format": "immich-cn.dataset/1", "schemaVersion": 1}),
        )
        archive.writestr("NOTICE.txt", "GeoNames CC BY 4.0\n")
        archive.writestr("README.txt", "canonical dataset\n")
    database.unlink()

    def asset(path: Path, kind: str) -> dict[str, object]:
        return {
            "file": path.name,
            "kind": kind,
            "sizeBytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    artifact_spec = [
        {
            "id": "immich-cn.geodata.admin2.default.v1",
            "file": geodata_default.name,
            "canonicalFile": "immich-cn-geodata-admin2-default-v1.zip",
            "profile": "admin2",
            "scope": "default",
            "sizeBytes": geodata_default.stat().st_size,
            "sha256": hashlib.sha256(geodata_default.read_bytes()).hexdigest(),
        },
        {
            "id": "immich-cn.geodata.admin2.full.v1",
            "file": geodata_full.name,
            "canonicalFile": "immich-cn-geodata-admin2-full-v1.zip",
            "profile": "admin2",
            "scope": "full",
            "sizeBytes": geodata_full.stat().st_size,
            "sha256": hashlib.sha256(geodata_full.read_bytes()).hexdigest(),
        },
    ]
    manifest_path = dist / "immich-cn-manifest-json-v1.json"
    assets = [
        asset(geodata_default, "geodata"),
        asset(geodata_full, "geodata"),
        asset(patterns, "patterns"),
        asset(i18n, "i18n"),
        asset(dataset, "dataset"),
    ]
    manifest_path.write_text(
        json.dumps(
            {
                "artifactSpecVersion": 4,
                "artifacts": artifact_spec,
                "assets": assets,
                "patternsTable": patterns.name,
                "dataset": {"file": dataset.name},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    checksums = [*assets, asset(manifest_path, "manifest")]
    (dist / "immich-cn-checksums-sha256-v1.txt").write_text(
        "".join(f"{item['sha256']}  {item['file']}\n" for item in checksums),
        encoding="utf-8",
    )
    return dist


def test_check_artifacts_passes_on_minimal_dist(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    result = run_checker(tmp_path, "check_artifacts.py", str(dist))
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_artifacts_rejects_unregistered_dist_files(tmp_path: Path) -> None:
    """dist 里的历史残留会被 dist/* 一起发布，必须被拦下。"""
    dist = _make_dist(tmp_path)
    (dist / "geodata_admin_2.zip").write_bytes(b"legacy leftover")
    result = run_checker(tmp_path, "check_artifacts.py", str(dist))
    assert result.returncode == 1
    assert "未登记的残留文件" in result.stdout


def test_check_artifacts_detects_tampered_zip(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    target = dist / "immich-cn-patterns-tsv-v1.gz"  # 非 zip 制品：只有哈希层能发现
    original = target.read_bytes()
    # 同尺寸篡改：只翻转一个字节，确保"尺寸检查发现不了"
    middle = len(original) // 2
    tampered = bytearray(original)
    tampered[middle] ^= 0xFF
    target.write_bytes(bytes(tampered))
    assert target.stat().st_size == len(original)
    result = run_checker(tmp_path, "check_artifacts.py", str(dist))
    assert result.returncode == 1
    assert "immich-cn-patterns-tsv-v1.gz" in result.stdout


def test_check_artifacts_manifest_hash_layer(tmp_path: Path) -> None:
    """直接验证 manifest 哈希层：把它削弱后本用例必须失败。"""
    dist = _make_dist(tmp_path)
    target = dist / "immich-cn-patterns-tsv-v1.gz"
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0xFF
    target.write_bytes(bytes(data))
    errors: list[str] = []
    check_artifacts.check_manifest(dist, errors)
    assert any("immich-cn-patterns-tsv-v1.gz" in error for error in errors), errors


def test_check_artifacts_manifest_assets_cover_artifacts(tmp_path: Path) -> None:
    """artifacts 中登记的变体必须同时出现在 assets 清单中。"""
    dist = _make_dist(tmp_path)
    manifest_path = dist / "immich-cn-manifest-json-v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["assets"] = [
        asset for asset in manifest["assets"] if asset["file"] != "immich-cn-geodata-admin2-default-v1.zip"
    ]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    errors: list[str] = []
    check_artifacts.check_manifest(dist, errors)
    assert any("artifacts 未出现在 assets" in error for error in errors), errors


def test_check_artifacts_checksums_layer(tmp_path: Path) -> None:
    """直接验证 immich-cn-checksums-sha256-v1.txt 层：把它削弱后本用例必须失败。"""
    dist = _make_dist(tmp_path)
    target = dist / "immich-cn-patterns-tsv-v1.gz"
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0xFF
    target.write_bytes(bytes(data))
    errors: list[str] = []
    check_artifacts.check_checksums(dist, errors)
    assert any("immich-cn-patterns-tsv-v1.gz" in error for error in errors), errors


def test_check_artifacts_checksums_require_manifest_coverage(tmp_path: Path) -> None:
    """checksum 清单漏掉 manifest asset 时必须失败，不能只校验已列出的条目。"""
    dist = _make_dist(tmp_path)
    checksums = dist / "immich-cn-checksums-sha256-v1.txt"
    lines = [
        line
        for line in checksums.read_text(encoding="utf-8").splitlines()
        if not line.endswith("  immich-cn-patterns-tsv-v1.gz")
    ]
    checksums.write_text("\n".join(lines) + "\n", encoding="utf-8")

    errors: list[str] = []
    check_artifacts.check_checksums(dist, errors)
    assert any("未覆盖 manifest assets" in error for error in errors), errors


def test_check_artifacts_rejects_zip_path_traversal(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    with zipfile.ZipFile(dist / "immich-cn-geodata-admin2-default-v1.zip", "a") as archive:
        archive.writestr("../escape.txt", "escape")

    errors: list[str] = []
    check_artifacts.check_zips(dist, errors)
    assert any("路径越界" in error for error in errors), errors


def test_check_artifacts_rejects_zip_symlink(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    with zipfile.ZipFile(dist / "immich-cn-geodata-admin2-default-v1.zip", "a") as archive:
        info = zipfile.ZipInfo("geodata/link")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "../escape.txt")

    errors: list[str] = []
    check_artifacts.check_zips(dist, errors)
    assert any("符号链接" in error for error in errors), errors


def test_check_artifacts_rejects_zip_compression_bomb(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    with zipfile.ZipFile(dist / "immich-cn-geodata-admin2-default-v1.zip", "a") as archive:
        archive.writestr(
            "geodata/bomb.bin",
            b"\0" * (2 * 1024 * 1024),
            compress_type=zipfile.ZIP_DEFLATED,
        )

    errors: list[str] = []
    check_artifacts.check_zips(dist, errors)
    assert any("压缩比" in error for error in errors), errors


def test_check_artifacts_rejects_archive_uncompressed_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = _make_dist(tmp_path)
    monkeypatch.setattr(check_artifacts, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 1024)
    with zipfile.ZipFile(dist / "immich-cn-geodata-admin2-default-v1.zip", "a") as archive:
        archive.writestr("geodata/large.bin", b"\0" * 2048)

    errors: list[str] = []
    check_artifacts.check_zips(dist, errors)
    assert any("解压总量" in error for error in errors), errors


def test_check_artifacts_requires_i18n_license(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    with zipfile.ZipFile(dist / "immich-cn-i18n-json-v1.zip", "w") as archive:
        archive.writestr("langs/en.json", "{}")

    errors: list[str] = []
    check_artifacts.check_zips(dist, errors)
    assert any("缺少可读的 LICENSE" in error for error in errors), errors


def test_check_artifacts_requires_geodata_attribution(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    with zipfile.ZipFile(dist / "immich-cn-geodata-admin2-default-v1.zip", "w") as archive:
        archive.writestr("geodata/cities500.txt", "\t".join(["1"] + ["x"] * 18) + "\n")

    errors: list[str] = []
    check_artifacts.check_zips(dist, errors)
    assert any("geodata/NOTICE.txt" in error for error in errors), errors


def test_check_artifacts_reports_corrupt_zip_without_traceback(tmp_path: Path) -> None:
    """损坏的 zip 必须以校验错误呈现，而不是抛栈崩掉。"""
    dist = _make_dist(tmp_path)
    (dist / "immich-cn-geodata-admin2-default-v1.zip").write_bytes(b"this is not a zip file")
    result = run_checker(tmp_path, "check_artifacts.py", str(dist))
    assert result.returncode == 1
    assert "无法作为 zip 读取" in result.stdout
    assert "Traceback" not in result.stderr


def test_check_artifacts_rejects_dataset_schema_drift(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    target = dist / "immich-cn-dataset-sqlite-v1.zip"
    with zipfile.ZipFile(target) as source:
        members = {name: source.read(name) for name in source.namelist()}
    members["schema.json"] = json.dumps({"format": "immich-cn.dataset/2", "schemaVersion": 2}).encode()
    with zipfile.ZipFile(target, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    errors: list[str] = []
    check_artifacts.check_dataset(dist, errors)
    assert any("规范格式版本" in error for error in errors), errors


def test_check_artifacts_rejects_dataset_without_notice(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    with zipfile.ZipFile(dist / "immich-cn-dataset-sqlite-v1.zip", "w") as archive:
        archive.writestr("immich-cn-dataset-v1.sqlite", b"SQLite format 3\x00")
        archive.writestr("schema.json", json.dumps({"format": "immich-cn.dataset/1", "schemaVersion": 1}))
        archive.writestr("README.txt", "canonical dataset\n")
    errors: list[str] = []
    check_artifacts.check_dataset(dist, errors)
    assert any("缺少成员" in error and "NOTICE.txt" in error for error in errors), errors
