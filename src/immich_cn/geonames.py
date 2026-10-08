"""GeoNames 原始文件的流式解析。"""

from __future__ import annotations

import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from immich_cn.domain import (
    IDX_ADMIN1,
    IDX_ADMIN2,
    IDX_ADMIN3,
    IDX_ADMIN4,
    IDX_NAME,
    AdminEntry,
    Place,
)
from immich_cn.errors import ParseError
from immich_cn.logging_config import get_logger

logger = get_logger("geonames")

#: 我们会从国家全量 dump 中抽取的行政级别 feature code 及其层级。
ADMIN_FEATURE_LEVELS: dict[str, int] = {"ADM2": 2, "ADM2H": 2, "ADM3": 3, "ADM4": 4}


def read_admin_codes(path: Path) -> dict[str, AdminEntry]:
    """读取 admin1CodesASCII.txt / admin2Codes.txt。

    格式：``code \\t name \\t name ascii \\t geoname id``
    """
    entries: dict[str, AdminEntry] = {}
    if not path.exists():
        raise ParseError(f"缺少行政级别文件 {path}")
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 4:
                logger.warning("%s 第 %d 行字段不足，已跳过", path.name, line_number)
                continue
            geoname_raw = fields[3].strip()
            entries[fields[0]] = AdminEntry(
                name=fields[1],
                geoname_id=int(geoname_raw) if geoname_raw.isdigit() else None,
            )
    logger.info("读取 %s：%d 条", path.name, len(entries))
    return entries


def iter_places(path: Path, *, encoding: str = "utf-8") -> Iterator[Place]:
    """流式读取 places 文本（cities500.txt 或国家 dump），逐行产出。"""
    with path.open("r", encoding=encoding, errors="replace") as handle:
        for line in handle:
            place = Place.from_line(line)
            if place is not None:
                yield place


@dataclass(frozen=True, slots=True)
class AdminUnit:
    """从国家全量 dump 中抽取的行政单元（用于自建 admin3/admin4 表）。"""

    geoname_id: int
    name: str
    alternate_names: tuple[str, ...]


def build_admin_units(paths: Iterable[Path]) -> dict[int, dict[str, AdminUnit]]:
    """从国家 dump 中抽取 ADM2/ADM3/ADM4 记录，构造代码到行政单元的映射。

    GeoNames 只发布 admin1/admin2 的代码表，admin3/admin4 需要自行从各国家
    全量数据中的要素抽取；部分 admin2 代码也不在代码表中，同样从 ``ADM2``
    记录补齐。这也是本项目不依赖付费 API 也能给出区县、乡镇粒度的原因。
    """
    tables: dict[int, dict[str, AdminUnit]] = {2: {}, 3: {}, 4: {}}
    for path in paths:
        if not path.exists():
            continue
        for place in iter_places(path):
            level = ADMIN_FEATURE_LEVELS.get(place.feature_code)
            if level is None:
                continue
            code = place_code(place, level)
            if not code:
                continue
            tables[level][code] = AdminUnit(
                geoname_id=place.geoname_id,
                name=place.columns[IDX_NAME],
                alternate_names=tuple(place.alternate_names),
            )
        logger.info(
            "从 %s 抽取 admin2/admin3/admin4 记录后累计：%d / %d / %d",
            path.name,
            len(tables[2]),
            len(tables[3]),
            len(tables[4]),
        )
    return tables


def place_code(place: Place, level: int) -> str:
    """按行政层级拼出 ``CC.A1.A2[.A3[.A4]]`` 形式的代码。"""
    parts = [place.country_code, place.columns[IDX_ADMIN1]]
    if level >= 2:
        parts.append(place.columns[IDX_ADMIN2])
    if level >= 3:
        parts.append(place.columns[IDX_ADMIN3])
    if level >= 4:
        parts.append(place.columns[IDX_ADMIN4])
    if any(not part for part in parts):
        return ""
    return ".".join(parts)


def admin_code(country_code: str, admin1: str, admin2: str = "", admin3: str = "", admin4: str = "") -> str:
    """拼出用于查询行政级别表的 key。"""
    parts = [country_code, admin1]
    for value in (admin2, admin3, admin4):
        if not value:
            break
        parts.append(value)
    return ".".join(parts)


@dataclass(frozen=True, slots=True)
class CountryInfoRow:
    """countryInfo.txt 的一行。"""

    columns: list[str]

    @property
    def alpha2(self) -> str:
        return self.columns[0]

    @property
    def name(self) -> str:
        return self.columns[4]

    def with_name(self, name: str) -> CountryInfoRow:
        columns = list(self.columns)
        columns[4] = name
        return CountryInfoRow(columns=columns)

    def to_line(self) -> str:
        return "\t".join(self.columns)


def read_country_info(path: Path) -> list[CountryInfoRow]:
    """读取 countryInfo.txt，保留注释行顺序（注释通过 :func:`raw_lines` 处理）。"""
    rows: list[CountryInfoRow] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.rstrip("\r\n")
            if not stripped or stripped.startswith("#"):
                continue
            columns = stripped.split("\t")
            if len(columns) < 5:
                continue
            rows.append(CountryInfoRow(columns=columns))
    return rows


@dataclass(frozen=True, slots=True)
class AlternateName:
    """alternateNamesV2.txt 中与中文相关的一行。"""

    geoname_id: int
    language: str
    name: str
    preferred: bool
    historic: bool


def iter_alternate_names(
    path: Path,
    wanted: set[int] | None = None,
    *,
    language_filter: Callable[[str], bool] | None = None,
) -> Iterator[AlternateName]:
    """流式解析 alternateNamesV2.txt。

    ``wanted`` 非空时只产出与之相关的记录，避免把 1000 万行全部载入内存。
    """
    if not path.exists():
        raise ParseError(f"缺少 alternateNames 文件 {path}")
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number % 2_000_000 == 0:
                logger.debug("已解析 %d 行 alternateNames", line_number)
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 4:
                continue
            geoname_raw = fields[1]
            if not geoname_raw.isdigit():
                continue
            geoname_id = int(geoname_raw)
            if wanted is not None and geoname_id not in wanted:
                continue
            language = fields[2]
            if language_filter is not None and not language_filter(language):
                continue
            yield AlternateName(
                geoname_id=geoname_id,
                language=language,
                name=fields[3],
                preferred=len(fields) > 4 and fields[4] == "1",
                historic=len(fields) > 7 and fields[7] == "1",
            )


def extract_archive_member(archive: Path, member: str, destination: Path) -> Path:
    """从 zip 中解出单个成员到目标路径。"""
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        target_member = member
        if target_member not in names:
            # 有些归档把文件放在子目录里，做一次后缀匹配。
            candidates = [name for name in names if name.endswith(f"/{member}") or name == member]
            if not candidates:
                raise ParseError(f"{archive.name} 中未找到 {member}，实际包含：{names[:5]}")
            target_member = candidates[0]
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(target_member) as source, destination.open("wb") as sink:
            while chunk := source.read(1024 * 1024):
                sink.write(chunk)
    return destination


def safe_join(root: Path, relative: str) -> Path:
    """把归档成员名安全地拼接到 ``root`` 之下，拒绝任何越界路径。

    归档内容属于外部输入：即使成员名形如 ``a/../../evil``，写入位置也必须被限制在
    ``root`` 内，否则解包阶段就变成了可写入任意路径的漏洞（tar-slip）。
    """
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ParseError(f"归档成员路径越界，已拒绝：{relative!r}")
    return candidate
