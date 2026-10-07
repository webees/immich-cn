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

#: 仅作为构建参数、上游 Immich 契约或外部镜像契约，不需要在本项目运行时代码中出现的变量。
BUILD_ONLY = {
    "IMMICH_BASE",
    "IMMICH_HELMET_FILE",
    "IMMICH_VERSION",
    "IMMICH_CN_DATA_DATE",
    "IMMICH_CN_HTTP_PORT",
    "IMMICH_MACHINE_LEARNING_ENABLED",
}

#: 参与契约检查的文档（含贡献指南与安全策略，它们同样会引用路径与命令）
DOC_GLOBS = ("README.md", "docs/*.md", "CONTRIBUTING.md", "SECURITY.md")
#: 同样会被渲染成 Markdown 的附加文件：Release 说明、Issue 模板、示例注释。
RENDER_EXTRA_GLOBS = (
    ".github/*.md",
    ".github/ISSUE_TEMPLATE/*.yml",
    "examples/*.yml",
    "examples/nginx/*.conf",
)
CODE_GLOBS = (
    "src/**/*.py",
    "docker/*",
    "scripts/*",
    ".github/workflows/*.yml",
    ".github/*.md",
    "examples/*.yml",
    "examples/nginx/*.conf",
)

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
INDEPENDENCE_SECTION_END = "## Data model and usage"

#: 中国本地化是项目的主方向，README、专题文档、部署示例和时区默认值必须一致。
CHINA_LOCALIZATION_DOC = Path("docs/china-localization.md")
CHINA_LOCALIZATION_ANCHOR = "面向中国用户的 Immich 本地化增强套件"
CHINA_LOCALIZATION_PILLARS = ("显示", "检索", "地图", "体验", "加速", "数据")
CHINA_LOCALIZATION_PHASES = ("阶段 1", "阶段 2", "阶段 3", "阶段 4")
CHINA_TIMEZONE = "TZ: Asia/Shanghai"
CHINA_LOCALIZATION_OVERCLAIM = "完整行政区层级"
CHINA_ACCELERATION_DOC = Path("docs/china-acceleration.md")
CHINA_ACCELERATION_TOKENS = (
    "CDN",
    "jsDelivr",
    "cdn.jsdmirror.com",
    "IMMICH_CN_JSDELIVR_BASE",
    "jsdelivr_url.py",
    "Release 资产",
    "Cache-Control",
    "/_app/immutable/",
    "/api/",
)
TERMINOLOGY_DOC = Path("docs/terminology.md")
TECHNICAL_TERMS = (
    "artifact",
    "manifest",
    "checksum",
    "workflow",
    "pipeline",
    "cache",
    "coverage",
    "validation",
    "fingerprint",
    "release",
    "image",
    "digest",
    "provenance",
    "SBOM",
)

#: 时间承诺（“会在 N 天内回复”）无法保证，必须改为“通常”并注明不是承诺。
#: 已经带“通常”的句式视为合规，不再重复报警（否则护栏会自相矛盾）。
SLA_PROMISE = re.compile(r"(?<!通常)会\s*在\s*\d+\s*(?:个)?(?:天|日|小时|周|工作日)内")

#: Markdown 行内链接；只校验相对目标，外部 URL、锚点与 mailto 跳过。
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_LINK_PREFIXES = ("http://", "https://", "#", "mailto:")
#: CJK 与全角标点；用于检测 Markdown 软换行在中文之间渲染出空格。
CJK_CHAR = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")
#: 行首即新块（标题/列表/表格/代码围栏/HTML），不与上一行合并。
MD_BLOCK_START = re.compile(r"^(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|~~~|<|-{3,}$|={3,}$)")
#: 中文标点后紧跟空格：YAML 折叠标量把中文描述折行时会产生这种痕迹。
CJK_PUNCT_SPACE = re.compile(r"[、，。；：！？]\s")
ASSET_TOKEN = re.compile(r"\bimmich-cn-[A-Za-z0-9._<>-]+")
CANONICAL_GEODATA = re.compile(r"^immich-cn-geodata-[a-z0-9-]+-(default|full)-v[0-9]+\.zip$")
INTERNAL_FILES = {"immich-cn-patterns-v1.tsv"}
LEGACY_ASSET_PREFIXES = ("geodata_admin_", "geodata_full", "geodata.zip")

#: 价值完全依赖"能被找到"的文件：必须在 README 或 docs 中被引用，否则等于隐藏文件。
DISCOVERABLE_GLOBS = ("NOTICE", "examples/*.yml", "examples/nginx/*.conf", "docs/*.md")

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


#: 需要在 docs/development.md 表格中标注默认值的环境变量及其实现位置。
ENV_DEFAULT_FILES = {
    "IMMICH_CN_AMAP_QPS": Path("src/immich_cn/providers/amap.py"),
    "IMMICH_CN_AMAP_BATCH_SIZE": Path("src/immich_cn/providers/amap.py"),
    "IMMICH_CN_NOMINATIM_QPS": Path("src/immich_cn/providers/nominatim.py"),
    "IMMICH_CN_LOG_LEVEL": Path("src/immich_cn/logging_config.py"),
}
#: 默认值来自模块级 DEFAULT_COUNTRIES 常量的环境变量。
ENV_DEFAULT_COUNTRY_FILES = {
    "IMMICH_CN_AMAP_COUNTRIES": Path("src/immich_cn/providers/amap.py"),
    "IMMICH_CN_NOMINATIM_COUNTRIES": Path("src/immich_cn/providers/nominatim.py"),
}


def _implemented_env_defaults() -> dict[str, str]:
    """从实现源码解析文档表格需要标注的环境变量默认值。"""
    defaults: dict[str, str] = {}
    for name, path in ENV_DEFAULT_FILES.items():
        text = path.read_text(encoding="utf-8")
        match = re.search(rf'positive_int_env\(\s*"{name}"\s*,\s*(\d+)\s*\)', text)
        if match is None:
            match = re.search(rf'environ\.get\(\s*"{name}"\s*,\s*"([^"]*)"', text)
        if match is not None:
            defaults[name] = match.group(1)
    for name, path in ENV_DEFAULT_COUNTRY_FILES.items():
        codes = re.search(r"DEFAULT_COUNTRIES = \(([^)]*)\)", path.read_text(encoding="utf-8"))
        if codes is not None:
            defaults[name] = ",".join(re.findall(r'"([A-Za-z]{2})"', codes.group(1)))
    return defaults


def check_env_defaults(errors: list[str]) -> None:
    """docs/development.md 记录的环境变量默认值必须与实现一致。"""
    path = Path("docs/development.md")
    rows = re.findall(
        r"^\|\s*`(IMMICH_[A-Z0-9_]+)`\s*\|\s*`([^`]*)`\s*\|",
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    documented = dict(rows)
    implemented = _implemented_env_defaults()
    if not implemented:
        errors.append("未能从实现源码解析到环境变量默认值，护栏可能已失效")
        return
    for name, expected in sorted(implemented.items()):
        if name not in documented:
            errors.append(f"docs/development.md 缺少 {name} 的默认值行（实现默认 {expected!r}）")
        elif documented[name] != expected:
            errors.append(f"docs/development.md 记录 {name} 默认 {documented[name]!r}，实现为 {expected!r}")


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
    for match in re.finditer(r"(\d+)\s*个\s*geodata\s+(?:变体|variant)", doc_text):
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


def check_china_localization_contract(errors: list[str]) -> None:
    """中国本地化定位必须可发现、覆盖六个支柱，并给出中国时区默认值。"""
    readme = Path("README.md").read_text(encoding="utf-8")
    if CHINA_LOCALIZATION_ANCHOR not in readme:
        errors.append(f"README 缺少中国本地化定位锚点：{CHINA_LOCALIZATION_ANCHOR}")
    if "docs/china-localization.md" not in readme:
        errors.append("README 必须链接 docs/china-localization.md，说明本地化边界与路线图")
    if "docs/china-acceleration.md" not in readme:
        errors.append("README 必须链接 docs/china-acceleration.md，说明 CDN 与静态资源加速边界")
    if CHINA_LOCALIZATION_OVERCLAIM in readme:
        errors.append(f"README 不应把当前未完成的目标写成既成事实：{CHINA_LOCALIZATION_OVERCLAIM}")

    if not CHINA_LOCALIZATION_DOC.exists():
        errors.append(f"缺失中国本地化专题文档：{CHINA_LOCALIZATION_DOC}")
        return
    doc = CHINA_LOCALIZATION_DOC.read_text(encoding="utf-8")
    for pillar in CHINA_LOCALIZATION_PILLARS:
        if f"| {pillar} |" not in doc:
            errors.append(f"{CHINA_LOCALIZATION_DOC} 的六支柱表缺少「{pillar}」行")
    for phase in CHINA_LOCALIZATION_PHASES:
        if phase not in doc:
            errors.append(f"{CHINA_LOCALIZATION_DOC} 缺少路线图阶段：{phase}")

    if not CHINA_ACCELERATION_DOC.exists():
        errors.append(f"缺失中国加速专题文档：{CHINA_ACCELERATION_DOC}")
    else:
        acceleration = CHINA_ACCELERATION_DOC.read_text(encoding="utf-8")
        missing = [token for token in CHINA_ACCELERATION_TOKENS if token not in acceleration]
        if missing:
            errors.append(f"{CHINA_ACCELERATION_DOC} 缺少加速边界：{'、'.join(missing)}")
        for example in ("../examples/compose.acceleration.yml", "../examples/nginx/immich-cn.conf"):
            if example not in acceleration:
                errors.append(f"{CHINA_ACCELERATION_DOC} 未引用可执行示例：{example}")

    for path in (Path("docs/deployment.md"), *sorted(Path("examples").glob("*.yml"))):
        if CHINA_TIMEZONE not in path.read_text(encoding="utf-8"):
            errors.append(f"{path} 缺少中国本地化默认时区：{CHINA_TIMEZONE}")


def check_documentation_language(errors: list[str]) -> None:
    """GitHub 页面短标签和技术术语必须使用英文，并保留术语规范入口。"""
    readme = Path("README.md").read_text(encoding="utf-8")
    if "[![Data Update]" not in readme:
        errors.append("README 的 data update badge alt text 必须使用英文简写 [![Data Update]")
    if "[![全自动更新数据]" in readme:
        errors.append("README 的 data update badge 仍使用过长的中文 alt text")
    if "docs/terminology.md" not in readme:
        errors.append("README 必须链接 docs/terminology.md，明确技术术语使用英文")
    if not TERMINOLOGY_DOC.exists():
        errors.append(f"缺失技术术语规范：{TERMINOLOGY_DOC}")
        return
    terminology = TERMINOLOGY_DOC.read_text(encoding="utf-8")
    missing = [term for term in TECHNICAL_TERMS if f"| `{term}` |" not in terminology]
    if missing:
        errors.append(f"{TERMINOLOGY_DOC} 术语表缺少英文核心术语：{'、'.join(missing)}")


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


def _manifest_top_level_keys() -> set[str]:
    """从实现提取 manifest 顶层字段：as_manifest 的返回字面量与 packaging 的赋值。"""
    import ast

    keys: set[str] = set()
    tree = ast.parse(Path("src/immich_cn/pipeline.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "as_manifest":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                    keys.update(key.value for key in sub.value.keys if isinstance(key, ast.Constant))
    packaging = Path("src/immich_cn/packaging.py").read_text(encoding="utf-8")
    keys.update(re.findall(r'manifest\["([A-Za-z0-9_]+)"\]\s*=', packaging))
    return keys


def check_manifest_field_docs(errors: list[str]) -> None:
    """docs/artifact-spec.md 必须记录 manifest 的每个顶层字段。"""
    doc = Path("docs/artifact-spec.md").read_text(encoding="utf-8")
    keys = _manifest_top_level_keys()
    if not keys:
        errors.append("未能从实现提取 manifest 顶层字段，护栏可能已失效")
        return
    for key in sorted(keys):
        if key not in doc:
            errors.append(f"docs/artifact-spec.md 未记录 manifest 顶层字段：{key}")


def check_manifest_stats_scope(errors: list[str]) -> None:
    """manifest 的 stats 是规范层 full 口径，文档必须写明，否则会被当成某个 zip 的行数。"""
    path = Path("docs/artifact-spec.md")
    doc = path.read_text(encoding="utf-8")
    if "stats" not in doc:
        return  # 顶层字段护栏已保证 stats 出现，这里只在该前提成立时补充口径要求
    required = (
        "sourcePlaces",
        "extraPlaces",
        "outputPlaces",
        "droppedCities",
        "droppedExtra",
        "cities500.txt",
    )
    missing = [token for token in required if token not in doc]
    if missing:
        errors.append(
            f"{path} 未说明 stats 口径，缺少：{'、'.join(missing)}（stats 是规范层 full 口径，不等于某个 zip 的行数）"
        )


def check_cjk_soft_breaks(doc_files: list[Path], errors: list[str]) -> None:
    """中文段落内的软换行会被 Markdown 渲染成空格，必须合并为单行。"""
    checked = 0
    for path in doc_files:
        lines = path.read_text(encoding="utf-8").splitlines()
        in_fence = False
        for index in range(len(lines) - 1):
            raw = lines[index]
            if raw.strip().startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            current = raw.rstrip()
            following = lines[index + 1].strip()
            if not current or not following:
                continue
            if current.strip().startswith(">") and following.startswith(">"):
                left = re.sub(r"^\s*>+\s?", "", current.strip())
                right = re.sub(r"^\s*>+\s?", "", following)
                checked += 1
                if left and right and CJK_CHAR.search(left[-1]) and CJK_CHAR.search(right[0]):
                    errors.append(f"{path}:{index + 2} 引用块内的中文软换行会在渲染时插入空格，请合并为一行")
                continue
            if MD_BLOCK_START.match(following):
                continue
            checked += 1
            if CJK_CHAR.search(current[-1]) and CJK_CHAR.search(following[0]):
                errors.append(f"{path}:{index + 2} 中文软换行会在渲染时插入空格，请与本段合并为一行")
    if checked == 0:
        errors.append("CJK 软换行检查未扫描到任何续行，护栏可能已失效")


def check_citation_spacing(errors: list[str]) -> None:
    """CITATION.cff 的字符串不应在中文标点后出现空格（YAML 折叠标量会引入）。"""
    try:
        import yaml
    except ModuleNotFoundError:  # pragma: no cover - 依赖已在 dev extra 中声明
        errors.append("缺少 PyYAML，无法校验 CITATION.cff")
        return

    path = Path("CITATION.cff")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        errors.append(f"{path} 不是合法 YAML：{error}")
        return

    def strings(value: object):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    for text in strings(data):
        match = CJK_PUNCT_SPACE.search(text)
        if match:
            errors.append(
                f"{path} 的字符串在中文标点后出现空格（{match.group(0)!r}）：{text[:40]!r}"
                "；YAML 折叠标量折行会引入空格，请写成单行"
            )
            break


#: Immich 改读 countryInfo.txt 的分界点，经上游源码核对：v3.0.0 ~ v3.2.4 仍在
#: `map.repository.ts` 里 `import { getName } from 'i18n-iso-countries'`，v3.3.0 才移除并改读 countryInfo。
COUNTRYINFO_BOUNDARY = "3.3.0 起改读 countryInfo.txt"
#: 前置负向断言避免把正确的「3.3.0 起改读」误判为过时的「3.0 起改读」。
COUNTRYINFO_STALE = re.compile(r"(?<![0-9.])(3\.0 起改读|1\.136\.0 ~ 2\.x)")


#: ADM4 覆盖的常见误读写法：把「要素数量」说成「代码数量」，或断言 GeoNames 几乎没有乡镇要素。
ADM4_MISLEADING = ("几乎没有乡镇级", "ADM4（乡镇）在 GeoNames 中仅 73 条")


def check_adm4_coverage_wording(paths: list[Path], errors: list[str]) -> None:
    """ADM4 的表述必须区分「要素数量」与「带 admin4 代码的数量」。

    实测（2026-10-07，CN.txt sha256 10b1e064…）：中国大陆 dump 有 11,878 条 ADM4 要素，
    但只有 73 条带 admin4 代码。原表述「在 GeoNames 中仅 73 条」把代码数写成了要素数，
    会让读者以为上游没有乡镇数据，进而误判离线方案的上限。
    """
    claims = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for phrase in ADM4_MISLEADING:
            if phrase in text:
                errors.append(f"{path} 使用会被误读的 ADM4 表述（{phrase}）；应区分要素数与带 admin4 代码的数量")
        if "73 条" in text and "ADM4" in text:
            claims += 1
            if "admin4" not in text:
                errors.append(f"{path} 提到 ADM4 的 73 条，但未说明这是「带 admin4 代码的数量」")
    if claims == 0:
        errors.append("没有文档说明 ADM4 的代码覆盖限制，护栏可能已失效")


def check_immich_countryinfo_boundary(paths: list[Path], errors: list[str]) -> None:
    """Immich 国家名来源的版本分界必须写对（上游核对为 3.3.0，而非 3.0）。"""
    claims = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        stale = COUNTRYINFO_STALE.search(text)
        if stale:
            errors.append(f"{path} 使用过时的 Immich 版本分界（{stale.group(0)}）；核对结果为 {COUNTRYINFO_BOUNDARY}")
        if "改读 countryInfo.txt" in text:
            claims += 1
            if COUNTRYINFO_BOUNDARY not in text:
                errors.append(f"{path} 提到 countryInfo.txt 但未写明分界；应写 {COUNTRYINFO_BOUNDARY}")
    if claims == 0:
        errors.append("没有任何文档声明 Immich 改读 countryInfo.txt 的版本分界，护栏可能已失效")


def check_dataset_member_doc(errors: list[str]) -> None:
    """docs/data-format.md 的归档成员名必须与实现的 DATASET_MEMBER 一致。

    文档曾写成构建期的中间文件名 `dataset.sqlite`，用户照抄会得到一个空库并报
    `no such table: localized_places`。
    """
    sys.path.insert(0, str(Path("src").resolve()))
    from immich_cn.artifact_spec import DATASET_MEMBER

    path = Path("docs/data-format.md")
    doc = path.read_text(encoding="utf-8")
    if f"`{DATASET_MEMBER}`" not in doc:
        errors.append(f"{path} 未用反引号记录数据集归档成员 {DATASET_MEMBER!r}（应写归档内文件名，而不是中间产物名）")
    for name in re.findall(r"sqlite3\s+([^\s\\]+)", doc):
        if name != DATASET_MEMBER:
            errors.append(f"{path} 的 sqlite3 示例使用 {name!r}，与归档成员 {DATASET_MEMBER!r} 不一致")


def check_i18n_asset_documented(paths: list[Path], errors: list[str]) -> None:
    """面向 Release 下载的文档必须说明 i18n 覆盖包是独立资产。

    `immich-cn-i18n-json-v1.zip` 与 geodata zip 分开发布，geodata zip 里没有 `langs/`；
    只下载 geodata 会让 Immich 1.136.0 ~ 3.2.x 缺少国家名覆盖。
    """
    required = {"README.md", "docs/deployment.md"}
    seen: set[str] = set()
    for path in paths:
        text = path.read_text(encoding="utf-8")
        # 同时接受仓库相对路径与绝对路径（便于单元测试直接传入临时文件）
        label = "README.md" if path.name == "README.md" else "docs/deployment.md"
        if "i18n-iso-countries/langs" not in text:
            continue
        if label in required and (path.name == "README.md" or path.as_posix().endswith("docs/deployment.md")):
            seen.add(label)
            if "immich-cn-i18n-json-v1.zip" not in text:
                errors.append(
                    f"{path} 要求挂载 i18n-iso-countries/langs，但未说明需单独下载 immich-cn-i18n-json-v1.zip"
                )
    missing = sorted(required - seen)
    if missing:
        errors.append(f"以下文档未提及 i18n 挂载契约，护栏可能已失效：{'、'.join(missing)}")


def check_geodata_import_wording(paths: list[Path], errors: list[str]) -> None:
    """描述 Immich geodata 重新导入条件时不能写成「按新旧比较」。

    上游 map.repository.ts 的判断是 `geocodingMetadata?.lastUpdate === geodataDate`
    就 return：与上次记录**相等**才跳过，任何不同的值（更新或更旧）都会重新导入。
    """
    stale_phrases = ("比上次导入时间更新", "不新于上次导入时间")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for phrase in stale_phrases:
            if phrase in text:
                errors.append(
                    f"{path} 使用了不准确的导入条件（{phrase}）；上游是「与上次记录相等则跳过，否则重新导入」"
                )


#: 香港 18 个区议会分区及官方所属区域；缺一个就会让该区地名丢掉「香港岛/九龙/新界」前缀。
HK_DISTRICTS = {
    "中西区": "香港岛",
    "湾仔区": "香港岛",
    "东区": "香港岛",
    "南区": "香港岛",
    "油尖旺区": "九龙",
    "深水埗区": "九龙",
    "九龙城区": "九龙",
    "黄大仙区": "九龙",
    "观塘区": "九龙",
    "葵青区": "新界",
    "荃湾区": "新界",
    "屯门区": "新界",
    "元朗区": "新界",
    "北区": "新界",
    "大埔区": "新界",
    "沙田区": "新界",
    "西贡区": "新界",
    "离岛区": "新界",
}


def check_hk_districts(errors: list[str]) -> None:
    """config/overrides.toml 的 hk_districts 必须覆盖香港 18 区且区域归属正确。"""
    from immich_cn.localization import NameOverrides

    mapping = NameOverrides.load(Path("config/overrides.toml")).hk_districts
    missing = sorted(name for name in HK_DISTRICTS if name not in mapping)
    if missing:
        errors.append(
            f"hk_districts 缺少香港区议会分区：{'、'.join(missing)}（这些区名会丢失「香港岛/九龙/新界」前缀）"
        )
    wrong = sorted(
        f"{name}→{mapping[name]}"
        for name, region in HK_DISTRICTS.items()
        if name in mapping and mapping[name] != region
    )
    if wrong:
        errors.append(f"hk_districts 的区域归属与官方划分不符：{'、'.join(wrong)}")


def check_language_priority_doc(errors: list[str]) -> None:
    """docs/data-sources.md 的中文语言优先级链必须与实现同序。

    这条链决定同一个地名在多个中文别名里选哪一个（zh-Hans 优先于 zh-Hant 等），
    实现是 `localization.LANGUAGE_PRIORITY`；文档抄错或实现被重排都会静默改变选名结果。
    """
    from immich_cn.localization import LANGUAGE_PRIORITY

    path = Path("docs/data-sources.md")
    doc = path.read_text(encoding="utf-8")
    # 链本身可能被抄错顺序（例如首项不再是 zh-Hans），所以不能把首项写死
    chain = r"zh(?:-[A-Za-z]+)*"
    match = re.search(rf"^\s*({chain}(?:\s*>\s*{chain})+)\s*$", doc, re.MULTILINE)
    if match is None:
        errors.append(f"{path} 未列出中文语言优先级链，护栏可能已失效")
        return
    documented = [item.strip().lower() for item in match.group(1).split(">")]
    actual = [item.lower() for item in LANGUAGE_PRIORITY]
    if documented != actual:
        errors.append(f"{path} 的中文语言优先级与实现不一致：文档 {documented}，实现 {actual}")


def check_license_consistency(errors: list[str]) -> None:
    """代码许可声明必须在 LICENSE / pyproject / CITATION / NOTICE / licensing 之间一致。

    代码是 MIT，但数据制品不是；两句话一旦在某一处丢失或改错，会直接影响使用者的
    合规判断（pyproject 的 license 还会进入发布元数据）。
    """
    import tomllib

    problems: list[str] = []
    license_text = Path("LICENSE").read_text(encoding="utf-8").lstrip()
    if not license_text.startswith("MIT License"):
        problems.append("LICENSE 不是 MIT 文本")

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    py_license = str((pyproject.get("project") or {}).get("license", ""))
    if py_license != "MIT":
        problems.append(f"pyproject.toml 的 license 是 {py_license!r}，不是 MIT")

    cff = re.search(
        r"^license:\s*(\S+)\s*$",
        Path("CITATION.cff").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if cff is None or cff.group(1) != "MIT":
        problems.append("CITATION.cff 的 license 不是 MIT")

    # 两处都必须同时给出「代码 MIT」与「数据制品不适用纯 MIT」，用固定措辞避免偶然命中
    for path, phrase in {
        Path("NOTICE"): "并不属于 MIT",
        Path("docs/licensing.md"): "数据制品不适用 MIT",
    }.items():
        text = path.read_text(encoding="utf-8")
        if "MIT" not in text:
            problems.append(f"{path} 未说明 MIT")
        elif phrase not in text:
            problems.append(f"{path} 未说明数据制品不适用纯 MIT（缺少「{phrase}」）")

    if problems:
        errors.append("许可声明不一致：" + "；".join(problems))


def check_version_consistency(errors: list[str]) -> None:
    """项目版本号必须在 pyproject / __init__ / CITATION 三处一致。

    release.yml 只把用户输入的版本与 pyproject 比对；而镜像的 OCI version 取自
    包的 ``__version__``、Release tag 取自输入版本。三者一旦漂移，会出现「tag 是
    1.0.5、镜像 OCI version 是 1.0.4」这类不一致。
    """
    import tomllib

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    init_text = Path("src/immich_cn/__init__.py").read_text(encoding="utf-8")
    citation_text = Path("CITATION.cff").read_text(encoding="utf-8")
    init_match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    cff_match = re.search(r"^version:\s*(\S+)\s*$", citation_text, re.MULTILINE)
    versions = {
        "pyproject.toml": str((pyproject.get("project") or {}).get("version", "")),
        "src/immich_cn/__init__.py": init_match.group(1) if init_match else "",
        "CITATION.cff": cff_match.group(1) if cff_match else "",
    }
    if not all(versions.values()):
        errors.append(f"无法从以下文件解析出项目版本号：{versions}")
        return
    if len(set(versions.values())) > 1:
        errors.append("项目版本号不一致：" + "、".join(f"{name}={value}" for name, value in versions.items()))


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
    check_env_defaults(errors)
    check_cli(doc_text, errors)
    check_make(doc_text, errors)
    check_langs_mounts(doc_files + _expand(("examples/*.yml",)), errors)
    check_discoverable(errors)
    check_numeric_contracts(errors)
    check_source_contracts(errors)
    check_module_name_table(errors)
    check_referenced_paths(doc_files, errors)
    check_project_positioning(errors)
    check_china_localization_contract(errors)
    check_documentation_language(errors)
    check_absolute_claims([*doc_files, Path("CITATION.cff")], errors)
    check_process_or_legal_claims([*doc_files, Path("CITATION.cff")], errors)
    check_independence_guidance(errors)
    check_sla_promises([*doc_files, Path("CITATION.cff")], errors)
    check_markdown_links(doc_files, errors)
    check_manifest_field_docs(errors)
    check_manifest_stats_scope(errors)
    render_files = [*doc_files, *_expand(RENDER_EXTRA_GLOBS)]
    check_cjk_soft_breaks(render_files, errors)
    check_citation_spacing(errors)
    check_dataset_member_doc(errors)
    check_immich_countryinfo_boundary(render_files, errors)
    check_adm4_coverage_wording(render_files, errors)
    check_i18n_asset_documented(render_files, errors)
    check_version_consistency(errors)
    check_license_consistency(errors)
    check_geodata_import_wording(render_files, errors)
    check_language_priority_doc(errors)
    check_hk_districts(errors)
    check_asset_names(render_files, errors)

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
