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

#: 仅作为构建参数或外部镜像契约，不需要在本项目运行时文档中出现的变量。
BUILD_ONLY = {
    "IMMICH_BASE",
    "IMMICH_VERSION",
    "IMMICH_CN_DATA_DATE",
    "IMMICH_MACHINE_LEARNING_ENABLED",
}

#: 参与契约检查的文档（含贡献指南与安全策略，它们同样会引用路径与命令）
DOC_GLOBS = ("README.md", "docs/*.md", "CONTRIBUTING.md", "SECURITY.md")
CODE_GLOBS = ("src/**/*.py", "docker/*", "scripts/*", ".github/workflows/*.yml", ".github/*.md", "examples/*.yml")

ENV_PATTERN = re.compile(r"\b(IMMICH_[A-Z0-9_]+)\b")
# 只允许行内空白，避免把「上一行以 immich-cn 结尾、下一行以别的单词开头」误判成子命令
CLI_PATTERN = re.compile(r"(?:^|[ \t`(])immich-cn[ \t]+([a-z-]+)((?:[ \t]+--[a-z-]+)*)", re.MULTILINE)
MAKE_PATTERN = re.compile(r"(?:^|[ \t`(])make[ \t]+([a-z][a-z-]{2,})", re.MULTILINE)
LANGS_PATH = "/i18n-iso-countries/langs"
FIRST_DOWNLOAD_MIB = 260
FORBIDDEN_POSITIONING = (
    "独立重写版本",
    "在保留相同数据格式与使用方式的前提下",
)
ABSOLUTE_CLAIMS = {
    "完全独立": "改用“独立实现”，并说明当前树与依赖事实",
    "完全无人值守": "改用“按设计无人值守”，并写明运行前提",
    "绝不会输出空": "改为按非空层级回退，并说明全空记录的校验边界",
    "不会发布坏数据": "改为已实现检查失败会阻断发布，不声称覆盖所有潜在缺陷",
    "零密钥": "改为“无需 API Key”，并说明默认 provider 的依赖",
}

#: 独立性声明只能写“当前树可核查事实”与“项目声明”。下面这些说法描述的是
#: 历史过程或法律状态，无法由当前提交验证，出现即视为文档缺陷。
PROCESS_OR_LEGAL_CLAIMS: dict[str, str] = {
    "也未从同类项目移植实现": "历史过程无法由当前树验证；改为限定扫描范围的核查结果",
    "未从同类项目移植": "历史过程无法由当前树验证；改为限定扫描范围的核查结果",
    "不是任何同类项目的重写版本": "历史过程且“任何”无法穷举；改为项目声明",
    "不是同类项目的重写版本": "历史过程无法由当前树验证；改为项目声明",
    "不包含、改写或复用": "过程断言；改为限定扫描范围的核查结果",
    "不包含任何同类项目": "“任何”无法穷举；改为限定扫描范围的核查结果",
    "不构成代码、数据或格式继承": "法律结论；改为描述消费者接口适配事实",
    "不构成任何格式继承": "法律结论；改为描述消费者接口适配事实",
    "不构成继承": "法律结论；改为描述消费者接口适配事实",
}

#: README 独立性段落的锚点；正文改写时需同步更新本契约。
INDEPENDENCE_ANCHOR = "本项目按独立实现组织"
INDEPENDENCE_SECTION_END = "## 数据模型与使用方式"

#: 时间承诺（“会在 N 天内回复”）无法保证，必须改为“通常”并注明不是承诺。
#: 已经带“通常”的句式视为合规，不再重复报警（否则护栏会自相矛盾）。
SLA_PROMISE = re.compile(r"(?<!通常)会\s*在\s*\d+\s*(?:个)?(?:天|日|小时|周|工作日)内")

#: Markdown 行内链接；只校验相对目标，外部 URL、锚点与 mailto 跳过。
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_LINK_PREFIXES = ("http://", "https://", "#", "mailto:")
ASSET_TOKEN = re.compile(r"\bimmich-cn-[A-Za-z0-9._<>-]+")
CANONICAL_GEODATA = re.compile(r"^immich-cn-geodata-[a-z0-9-]+-(default|full)-v[0-9]+\.zip$")
INTERNAL_FILES = {"immich-cn-patterns-v1.tsv"}
LEGACY_ASSET_PREFIXES = ("geodata_admin_", "geodata_full", "geodata.zip")

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

    def mentions(text: str, token: str) -> bool:
        pattern = rf"(?<![A-Za-z0-9_.-]){re.escape(token)}(?![A-Za-z0-9_.-])"
        return re.search(pattern, text) is not None

    for pattern in DISCOVERABLE_GLOBS:
        for path in sorted(Path().glob(pattern)):
            if not path.is_file():
                continue
            others = "\n".join(text for root, text in root_texts.items() if root != path)
            if not any(mentions(others, token) for token in (path.name, str(path))):
                errors.append(f"{path} 未被 README 或 docs 引用（用户无法发现）")


def check_numeric_contracts(errors: list[str]) -> None:
    """文档里的数字必须与实现一致（变体数、定时时刻、快照保留数量）。"""
    sys.path.insert(0, str(Path("src").resolve()))
    from immich_cn.packaging import build_variants
    from immich_cn.settings import DEFAULT_PATTERNS

    doc_text = _read(_expand(DOC_GLOBS))
    workflow = Path(".github/workflows/update-data.yml").read_text(encoding="utf-8")
    makefile = Path("Makefile").read_text(encoding="utf-8")

    if "镜像内置的是 full 数据集" in doc_text:
        errors.append("文档错误：镜像使用非 full 的 build/geodata，不能声称内置 full 数据集")
    if "默认在打包完成后删除" in doc_text:
        errors.append("文档错误：默认构建直接流式写 immich-cn-patterns-tsv-v1.gz，不生成明文 immich-cn-patterns-v1.tsv")

    expected_variants = len(build_variants(DEFAULT_PATTERNS))
    for match in re.finditer(r"(\d+)\s*个 geodata 变体", doc_text):
        if int(match.group(1)) != expected_variants:
            errors.append(f"文档称 {match.group(1)} 个 geodata 变体，实际生成 {expected_variants} 个")

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
        for match in re.finditer(r"保留最近\s*(\d+)\s*个\s*`data-\*`\s*快照", doc_text):
            if int(match.group(1)) != expected:
                errors.append(f"文档称保留最近 {match.group(1)} 个快照，实际默认 {expected}")

    make_download = re.search(r"build:.*?约\s*(\d+)\s*MiB", makefile)
    if not make_download:
        errors.append("Makefile 的 build 帮助未标注首次下载体积")
    elif int(make_download.group(1)) != FIRST_DOWNLOAD_MIB:
        errors.append(f"Makefile 称首次下载约 {make_download.group(1)} MiB，实际压缩下载约 {FIRST_DOWNLOAD_MIB} MiB")


def check_source_contracts(errors: list[str]) -> None:
    """上游数据源清单必须与 docs/data-sources.md 的表格同步。

    新增或重命名 `SourceSpec` 时必须同步文档，否则文档会静默描述一套不存在的源。
    """
    sys.path.insert(0, str(Path("src").resolve()))
    from immich_cn.settings import geonames_sources, i18n_sources, natural_earth_source

    doc = Path("docs/data-sources.md").read_text(encoding="utf-8")
    country_placeholder = "{CC}.zip"
    for source in [*geonames_sources(), natural_earth_source(), *i18n_sources()]:
        if source.name.startswith("country_dump_"):
            marker = country_placeholder
        elif source.name == "i18nIsoCountries":
            marker = "i18n-iso-countries"
        else:
            marker = source.cache_filename
        if marker not in doc:
            errors.append(f"上游数据源 {source.name} 未在 docs/data-sources.md 记录（期望出现 {marker!r}）")


#: docs/naming-conventions.md 的模块映射表行：| `old.py` | `current.py` | 职责 |
MODULE_TABLE_ROW = re.compile(
    r"^\|\s*`([a-z_][a-z0-9_]*\.py)`\s*\|\s*`([a-z_][a-z0-9_]*\.py)`\s*\|",
    re.MULTILINE,
)


def check_module_name_table(errors: list[str]) -> None:
    """命名规范表里的现行模块名必须存在，旧模块名必须已经消失。"""
    path = Path("docs/naming-conventions.md")
    rows = MODULE_TABLE_ROW.findall(path.read_text(encoding="utf-8"))
    if not rows:
        errors.append(f"{path} 的模块命名表未解析到任何映射，护栏可能已失效")
        return
    existing = {module.name for module in Path("src/immich_cn").rglob("*.py")}
    for legacy, current in rows:
        if current not in existing:
            errors.append(f"{path} 标记为现行模块名的 {current} 在 src/immich_cn 中不存在")
        if legacy in existing:
            errors.append(f"{path} 标记为旧模块名的 {legacy} 仍存在于 src/immich_cn 中")


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


def check_project_positioning(errors: list[str]) -> None:
    """项目定位必须保持独立实现，且上游启发只在 README 底部致谢中出现。"""
    readme = Path("README.md").read_text(encoding="utf-8")
    for phrase in FORBIDDEN_POSITIONING:
        if phrase in readme:
            errors.append(f"README 出现错误的项目定位：{phrase}")

    marker = "## 致谢"
    upstream = "https://github.com/ZingLix/immich-geodata-cn"
    positions = [index for index, line in enumerate(readme.splitlines(), start=1) if upstream in line]
    if len(positions) != 1:
        errors.append("README 对 ZingLix/immich-geodata-cn 的引用必须且只能出现在底部致谢中")
        return
    marker_line = next(
        (index for index, line in enumerate(readme.splitlines(), start=1) if line.strip() == marker),
        None,
    )
    if marker_line is None or positions[0] < marker_line:
        errors.append("对 ZingLix/immich-geodata-cn 的引用必须位于 README 底部致谢")


def check_absolute_claims(paths: list[Path], errors: list[str]) -> None:
    """拒绝没有范围、条件与例外的绝对化承诺。"""
    for path in paths:
        if path.name == "documentation-policy.md":
            continue
        text = path.read_text(encoding="utf-8")
        for phrase, replacement in ABSOLUTE_CLAIMS.items():
            if phrase in text:
                errors.append(f"{path} 使用绝对化表述 {phrase!r}；{replacement}")


def check_process_or_legal_claims(paths: list[Path], errors: list[str]) -> None:
    """拒绝无法从当前树验证的历史过程断言与法律结论。"""
    for path in paths:
        if path.name == "documentation-policy.md":
            continue
        text = path.read_text(encoding="utf-8")
        for phrase, replacement in PROCESS_OR_LEGAL_CLAIMS.items():
            if phrase in text:
                errors.append(f"{path} 出现不可验证或越界声明 {phrase!r}；{replacement}")


def check_independence_guidance(errors: list[str]) -> None:
    """README 的独立性声明必须标注为项目声明，并指向核查范围与边界。"""
    readme = Path("README.md").read_text(encoding="utf-8")
    head, _, _ = readme.partition(INDEPENDENCE_SECTION_END)
    if INDEPENDENCE_ANCHOR not in head:
        errors.append(f"README 独立性声明缺少锚点短语：{INDEPENDENCE_ANCHOR}")
    if "docs/documentation-policy.md" not in head:
        errors.append("README 独立性声明必须链接 docs/documentation-policy.md 的核查范围与边界")


def check_sla_promises(paths: list[Path], errors: list[str]) -> None:
    """拒绝无法保证的响应时间承诺。"""
    for path in paths:
        if path.name == "documentation-policy.md":
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = SLA_PROMISE.search(line)
            if match:
                errors.append(f"{path}:{line_number} 出现时间承诺 {match.group(0)!r}；改为“通常……，不是服务水平承诺”")


def check_markdown_links(doc_files: list[Path], errors: list[str]) -> None:
    """Markdown 相对链接必须指向仓库中真实存在的文件或目录。"""
    checked = 0
    for path in doc_files:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for raw in MARKDOWN_LINK.findall(line):
                target = raw.split("#")[0].strip()
                if not target or target.startswith(EXTERNAL_LINK_PREFIXES):
                    continue
                checked += 1
                if not (path.parent / target).resolve().exists():
                    errors.append(f"{path}:{line_number} 的 Markdown 链接目标不存在：{raw}")
    if checked == 0:
        errors.append("Markdown 链接检查未解析到任何相对链接，护栏可能已失效")


def check_asset_names(paths: list[Path], errors: list[str]) -> None:
    """文档中的发布资产名必须符合 v4 规范，且不能回退到 legacy 命名。"""
    sys.path.insert(0, str(Path("src").resolve()))
    from immich_cn.artifact_spec import (
        CHECKSUMS_FILE,
        DATASET_FILE,
        I18N_FILE,
        MANIFEST_FILE,
        PATTERNS_FILE,
    )

    allowed = {CHECKSUMS_FILE, DATASET_FILE, I18N_FILE, MANIFEST_FILE, PATTERNS_FILE, *INTERNAL_FILES}
    suffixes = (".zip", ".gz", ".json", ".txt")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in ASSET_TOKEN.findall(text):
            token = token.rstrip("。，,.)")
            if not token.endswith(suffixes):
                continue
            if "<" in token or ">" in token:
                continue
            if token.startswith("immich-cn-geodata-immich-"):
                errors.append(f"{path} 的资产名重复项目命名空间：{token}")
            elif any(legacy in token for legacy in LEGACY_ASSET_PREFIXES):
                errors.append(f"{path} 仍引用 legacy 资产名：{token}")
            elif token in allowed or CANONICAL_GEODATA.fullmatch(token):
                continue
            else:
                errors.append(f"{path} 使用未登记的发布资产名：{token}")


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
    check_source_contracts(errors)
    check_module_name_table(errors)
    check_referenced_paths(doc_files, errors)
    check_project_positioning(errors)
    check_absolute_claims([*doc_files, Path("CITATION.cff")], errors)
    check_process_or_legal_claims([*doc_files, Path("CITATION.cff")], errors)
    check_independence_guidance(errors)
    check_sla_promises([*doc_files, Path("CITATION.cff")], errors)
    check_markdown_links(doc_files, errors)
    check_asset_names(doc_files, errors)

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
