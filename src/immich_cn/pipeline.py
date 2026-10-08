"""构建流水线编排。

流水线被拆成可单独复用的阶段，便于在 CI 中定位失败点：

1. ``fetch``     下载并解压上游数据（GeoNames / Natural Earth / i18n-iso-countries）
2. ``scan``      扫描 cities500 与国家全量 dump，确定参与构建的地点集合
3. ``translate`` 解析 alternateNamesV2，构造中文名称索引与四级行政层级表
4. ``emit``      写出 geodata 目录与名称映射表
5. ``package``   生成各展示粒度 zip、校验和与 manifest
"""

from __future__ import annotations

import json
import os
import shutil
import tarfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import TextIO

from immich_cn import SCHEMA_VERSION, __version__
from immich_cn.display import compose, validate_pattern
from immich_cn.domain import AdminEntry, BuildStats, Place, SourceRecord
from immich_cn.errors import ImmichCnError, ParseError
from immich_cn.fetching import FetchedSource, Fetcher
from immich_cn.geonames import (
    AdminUnit,
    CountryInfoRow,
    admin_code,
    build_admin_units,
    extract_archive_member,
    iter_alternate_names,
    iter_places,
    read_admin_codes,
    read_country_info,
    safe_join,
)
from immich_cn.hierarchy import (
    Hierarchy,
    finalize_place_names,
    resolve_place_names,
    translate_admin_codes,
    translate_admin_units,
)
from immich_cn.localization import (
    SPECIAL_ADMIN_TOP_LEVEL,
    ChineseNameIndex,
    NameOverrides,
    build_name_index,
    is_japanese_language,
    language_rank,
    to_variant,
)
from immich_cn.logging_config import get_logger
from immich_cn.providers import ProviderChain, build_chain
from immich_cn.settings import (
    DEFAULT_PATTERN,
    FINE_GRAINED_ADMIN2,
    BuildOptions,
    ChineseVariant,
    SourceSpec,
    geonames_sources,
    i18n_sources,
    natural_earth_source,
)

logger = get_logger("build")

PROGRESS_EVERY = 500_000

#: 项目面向中国用户，构建日期与 manifest 时间统一写北京时间。
CHINA_TIMEZONE = timezone(timedelta(hours=8))

GEODATA_NOTICE = """immich-cn data attribution

- GeoNames data: https://www.geonames.org/ (CC BY 4.0)
- Natural Earth data: https://www.naturalearthdata.com/ (Public Domain)
- Optional OpenStreetMap/Nominatim data: https://www.openstreetmap.org/ (ODbL 1.0)
- Optional Amap-derived data: subject to Amap platform terms

Data processing by immich-cn: https://github.com/webees/immich-cn
Full notices: https://github.com/webees/immich-cn/blob/main/NOTICE
"""

#: GeoNames 中确实没有 admin1 层的国家/地区，允许其 admin1Code 为空。
COUNTRIES_WITHOUT_ADMIN1 = frozenset({"SG", "VA"})


@dataclass(frozen=True, slots=True)
class SourcePaths:
    """已就位的数据源路径。"""

    cities500: Path
    admin1: Path
    admin2: Path
    country_info: Path
    alternate_names: Path
    geojson: Path
    country_dumps: tuple[Path, ...]
    langs_dir: Path


@dataclass(slots=True)
class BuildResult:
    """一次构建的产物与统计。"""

    geodata_dir: Path
    cities500: Path
    names_file: Path
    extra_file: Path
    langs_dir: Path
    stats: BuildStats
    sources: list[SourceRecord]
    generated_at: str
    #: CI 发布器修订；上游数据未变化但构建逻辑变化时，必须触发重新发布。
    build_revision: str = ""
    provider_names: list[str] = field(default_factory=list)
    index_stats: dict[str, int] = field(default_factory=dict)
    admin_entries: dict[str, int] = field(default_factory=dict)
    build_config: dict[str, object] = field(default_factory=dict)

    def as_manifest(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "tool": {
                "name": "immich-cn",
                "version": __version__,
                "revision": self.build_revision,
            },
            "generatedAt": self.generated_at,
            "providers": self.provider_names,
            "stats": self.stats.as_dict(),
            "index": self.index_stats,
            "adminEntries": self.admin_entries,
            "config": self.build_config,
            "sources": [record.as_dict() for record in self.sources],
        }

    #: 打包完成后可以安全删除的中间文件（体积最大的一批）。
    removable_paths: list[Path] = field(default_factory=list)


def _validate_country_dumps(paths: tuple[Path, ...]) -> None:
    """配置的国家 dump 必须存在且能解析出 GeoNames 记录。

    `--skip-fetch` 直接使用 ``sources/`` 下的文件；文件缺失或名不副实（例如把 zip
    内容命名为 ``CN.txt``）时 ``build_admin_units`` 会跳过它并静默产出空的
    admin3/admin4，而其余校验仍会通过——本轮就踩到了这条路径。
    """
    for path in paths:
        if not path.exists():
            raise ParseError(f"缺少国家 dump：{path}（--skip-fetch 需要 sources/ 下已解压的 <CC>.txt）")
        found = False
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.count("\t") >= 18:
                    found = True
                    break
        if not found:
            raise ParseError(f"国家 dump 无法解析出记录：{path}（可能不是解压后的 GeoNames 文本）")


def run_build(options: BuildOptions) -> BuildResult:
    """执行完整构建，返回产物路径与统计。"""
    for pattern in options.patterns:
        validate_pattern(pattern)
    options.ensure_dirs()

    records = [] if options.skip_fetch else fetch_sources(options)
    paths = _source_paths(options)
    _validate_country_dumps(paths.country_dumps)
    overrides = NameOverrides.load(options.config_dir / "overrides.toml")

    stats = BuildStats()
    admin1_raw = read_admin_codes(paths.admin1)
    admin2_raw = read_admin_codes(paths.admin2)
    country_rows = read_country_info(paths.country_info)

    admin_units = build_admin_units(paths.country_dumps)
    stats.admin3_entries = len(admin_units[3])
    stats.admin4_entries = len(admin_units[4])

    cities500_file = options.work_dir / "cities500.txt"
    existing_ids, existing_locations, dropped_cities = _prepare_cities500(paths.cities500, cities500_file, admin1_raw)
    stats.dropped_places = dropped_cities
    stats.dropped_cities = dropped_cities
    stats.source_places = len(existing_ids)
    logger.info("cities500 有效记录：%d 条", stats.source_places)

    extra_file = options.work_dir / "extra_all.txt"
    extra_ids, dropped_extra = _select_extra_places(
        paths.country_dumps,
        extra_file,
        admin1_raw=admin1_raw,
        existing_ids=existing_ids,
        existing_locations=existing_locations,
    )
    stats.dropped_places += dropped_extra
    stats.dropped_extra = dropped_extra
    stats.extra_places = len(extra_ids)

    wanted = _wanted_geoname_ids(existing_ids, extra_ids, admin1_raw, admin2_raw, admin_units)
    index = build_name_index(
        _alternate_stream(paths.alternate_names, wanted),
        overrides=overrides,
        variant=options.chinese_variant,
    )
    stats.translated_names = len(index.names)

    hierarchy = _build_hierarchy(admin1_raw, admin2_raw, admin_units, index)
    stats.admin1_entries = len(hierarchy.admin1)
    stats.admin2_entries = len(hierarchy.admin2)
    logger.info("行政层级表：%s", hierarchy.as_stats())

    names_file = options.work_dir / "levels.tsv"
    chain = build_chain(options)
    country_names = _load_translations(paths.langs_dir, options.chinese_variant)
    try:
        chain.prefetch(iter_all_places(cities500_file, extra_file))
        _write_levels(
            names_file,
            cities500=cities500_file,
            extra_file=extra_file,
            hierarchy=hierarchy,
            index=index,
            overrides=overrides,
            chain=chain,
            country_names=country_names,
            min_population=options.min_population,
            stats=stats,
        )
    finally:
        chain.close()

    langs_dir = _write_langs(paths.langs_dir, options)
    generated_at = datetime.now(CHINA_TIMEZONE).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    _emit_geodata(
        options.geodata_dir,
        cities500=cities500_file,
        paths=paths,
        extra_file=extra_file,
        admin1_raw=admin1_raw,
        admin2_raw=admin2_raw,
        country_rows=country_rows,
        hierarchy=hierarchy,
        index=index,
        levels=load_levels(names_file),
        pattern=DEFAULT_PATTERN,
        full=False,
        min_population=options.min_population,
        generated_at=generated_at,
    )
    return BuildResult(
        geodata_dir=options.geodata_dir,
        cities500=cities500_file,
        names_file=names_file,
        extra_file=extra_file,
        langs_dir=langs_dir,
        stats=stats,
        sources=records,
        generated_at=generated_at,
        build_revision=os.environ.get("GITHUB_SHA", "").strip(),
        provider_names=chain.names,
        index_stats=index.stats(),
        admin_entries=hierarchy.as_stats(),
        build_config={
            "provider": options.resolve_provider(),
            "patterns": list(options.patterns),
            "extraCountries": list(options.extra_countries),
            "minPopulation": options.min_population,
            "chineseVariant": options.chinese_variant,
        },
        removable_paths=[paths.alternate_names, *paths.country_dumps],
    )


# --------------------------------------------------------------------------
# 阶段 1：获取数据源
# --------------------------------------------------------------------------


def fetch_sources(options: BuildOptions) -> list[SourceRecord]:
    """下载并解压所有上游数据源，返回指纹列表。"""
    specs: list[SourceSpec] = [
        *geonames_sources(options.extra_countries),
        natural_earth_source(),
        *i18n_sources(),
    ]
    fetched: list[FetchedSource] = []
    records: list[SourceRecord] = []
    with Fetcher(
        options.cache_dir,
        force=options.force_refresh,
        revalidate=options.revalidate,
    ) as fetcher:
        for spec in specs:
            try:
                result = fetcher.fetch(spec)
            except ImmichCnError as error:
                if spec.optional:
                    logger.warning("可选数据源 %s 获取失败，已跳过：%s", spec.name, error)
                    continue
                raise
            fetched.append(result)
            records.append(result.record)
    _materialize(fetched, options)
    return records


def _materialize(fetched: list[FetchedSource], options: BuildOptions) -> None:
    """把归档成员解出到 sources 目录。"""
    for result in fetched:
        spec = result.spec
        if spec.name == "i18nIsoCountries":
            _extract_i18n(result.path, options)
            continue
        extracted = False
        for member in spec.members:
            if not member.endswith(".txt"):
                continue
            destination = options.sources_dir / member
            if _is_current(spec, destination, result, options):
                continue
            extract_archive_member(result.path, member, destination)
            extracted = True
        if not spec.is_archive and not _is_current(spec, options.sources_dir / spec.filename, result, options):
            destination = options.sources_dir / spec.filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(result.path, destination)
            extracted = True
        if extracted or spec.is_archive:
            _write_stamp(spec, result, options)


def _write_stamp(spec: SourceSpec, result: FetchedSource, options: BuildOptions) -> None:
    stamp_dir = options.sources_dir / ".stamps"
    stamp_dir.mkdir(parents=True, exist_ok=True)
    (stamp_dir / f"{spec.name}.sha256").write_text(result.record.sha256 + "\n", encoding="utf-8")


def _is_current(
    spec: SourceSpec,
    destination: Path,
    result: FetchedSource,
    options: BuildOptions,
) -> bool:
    """用上游文件的 SHA256 作为解压标记，避免 mtime 带来的误判。"""
    if not destination.exists():
        return False
    stamp = options.sources_dir / ".stamps" / f"{spec.name}.sha256"
    if not stamp.exists():
        return False
    if stamp.read_text(encoding="utf-8").strip() != result.record.sha256:
        return False
    stamp.touch()
    return True


def _extract_i18n(archive: Path, options: BuildOptions) -> None:
    destination = options.work_dir / "i18n-iso-countries"
    license_target = destination / "LICENSE"
    if (destination / "langs" / "zh.json").exists() and license_target.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        files = [
            member
            for member in tar.getmembers()
            if (member.name.startswith("package/langs/") or member.name == "package/LICENSE") and member.isfile()
        ]
        if not files:
            raise ParseError(f"{archive.name} 中未找到 package/langs/ 目录")
        for member in files:
            target = safe_join(destination, member.name.removeprefix("package/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            with source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
    if not license_target.exists():
        raise ParseError(f"{archive.name} 中未找到 package/LICENSE，无法保留上游版权声明")
    logger.info("解出 i18n-iso-countries 语言文件：%d 个", len(list((destination / "langs").glob("*.json"))))


def _source_paths(options: BuildOptions) -> SourcePaths:
    sources = options.sources_dir
    paths = SourcePaths(
        cities500=_require(sources / "cities500.txt"),
        admin1=_require(sources / "admin1CodesASCII.txt"),
        admin2=_require(sources / "admin2Codes.txt"),
        country_info=_require(sources / "countryInfo.txt"),
        alternate_names=_require(sources / "alternateNamesV2.txt"),
        geojson=_require(sources / "ne_10m_admin_0_countries.geojson"),
        country_dumps=tuple(sources / f"{code}.txt" for code in options.extra_countries),
        langs_dir=options.work_dir / "i18n-iso-countries" / "langs",
    )
    if not paths.langs_dir.exists():
        raise ParseError(f"缺少语言文件目录 {paths.langs_dir}")
    return paths


def _require(path: Path) -> Path:
    if not path.exists():
        raise ParseError(f"缺少必要文件 {path}，请先执行 fetch")
    return path


def cleanup_removable(result: BuildResult, *, work_dir: Path) -> int:
    """删除工作目录内不再需要的中间文件，返回释放的字节数。"""
    freed = 0
    root = work_dir.resolve()
    for path in result.removable_paths:
        try:
            resolved = path.resolve()
            if resolved == root or root not in resolved.parents:
                logger.warning("拒绝清理工作目录外的文件 %s -> %s", path, resolved)
                continue
            freed += path.stat().st_size
            path.unlink()
        except OSError:
            continue
    if freed:
        logger.info("清理中间文件释放 %.1f MiB", freed / 1048576)
    return freed


# --------------------------------------------------------------------------
# 阶段 2：确定地点集合
# --------------------------------------------------------------------------


def keep_place(place: Place, admin1_raw: dict[str, AdminEntry]) -> bool:
    """过滤 GeoNames 中缺少有效一级行政区的噪声记录。"""
    if place.country_code in COUNTRIES_WITHOUT_ADMIN1:
        return True
    if not place.admin1_code:
        return False
    return f"{place.country_code}.{place.admin1_code}" in admin1_raw


def _prepare_cities500(
    path: Path,
    output: Path,
    admin1_raw: dict[str, AdminEntry],
) -> tuple[set[int], set[tuple[str, str]], int]:
    """过滤 cities500 并落盘为 canonical 版本，后续阶段只读这一份。"""
    ids: set[int] = set()
    locations: set[tuple[str, str]] = set()
    dropped = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as sink:
        for count, place in enumerate(iter_places(path), start=1):
            if not keep_place(place, admin1_raw):
                dropped += 1
                continue
            ids.add(place.geoname_id)
            locations.add(place.location_key)
            sink.write(place.to_line() + "\n")
            if count % PROGRESS_EVERY == 0:
                logger.info("扫描 cities500：%d 行", count)
    return ids, locations, dropped


def _select_extra_places(
    country_dumps: tuple[Path, ...],
    output: Path,
    *,
    admin1_raw: dict[str, AdminEntry],
    existing_ids: set[int],
    existing_locations: set[tuple[str, str]],
) -> tuple[set[int], int]:
    """把国家全量 dump 中不在 cities500 的记录写入 ``extra_all.txt``。

    这里保留全部候选，是否进入非 full 变体留到打包阶段按人口过滤，
    因此每个国家 dump 只需要扫描一次。
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    ids: set[int] = set()
    count = 0
    dropped = 0
    with output.open("w", encoding="utf-8") as sink:
        for path in country_dumps:
            if not path.exists():
                logger.warning("缺少国家 dump %s，已跳过", path)
                continue
            for place in iter_places(path):
                if not keep_place(place, admin1_raw):
                    dropped += 1
                    continue
                if place.geoname_id in existing_ids or place.location_key in existing_locations:
                    dropped += 1
                    continue
                existing_locations.add(place.location_key)
                ids.add(place.geoname_id)
                sink.write(place.to_line() + "\n")
                count += 1
                if count % PROGRESS_EVERY == 0:
                    logger.info("筛选额外地点：%d 条", count)
    logger.info("额外地点候选：%d 条", count)
    return ids, dropped


def _wanted_geoname_ids(
    existing_ids: set[int],
    extra_ids: set[int],
    admin1_raw: dict[str, AdminEntry],
    admin2_raw: dict[str, AdminEntry],
    admin_units: dict[int, dict[str, AdminUnit]],
) -> set[int]:
    wanted = set(existing_ids)
    wanted.update(extra_ids)
    for entries in (admin1_raw, admin2_raw):
        wanted.update(entry.geoname_id for entry in entries.values() if entry.geoname_id)
    for level in (3, 4):
        wanted.update(unit.geoname_id for unit in admin_units[level].values())
    return wanted


def _alternate_stream(path: Path, wanted: set[int]) -> Iterator[tuple[int, str, str, bool, bool]]:
    def wanted_language(language: str) -> bool:
        if not language or language[0] not in "zZjJ":
            return False
        return language_rank(language) is not None or is_japanese_language(language)

    for record in iter_alternate_names(path, wanted, language_filter=wanted_language):
        yield (record.geoname_id, record.language, record.name, record.preferred, record.historic)


# --------------------------------------------------------------------------
# 阶段 3：翻译
# --------------------------------------------------------------------------


def _build_hierarchy(
    admin1_raw: dict[str, AdminEntry],
    admin2_raw: dict[str, AdminEntry],
    admin_units: dict[int, dict[str, AdminUnit]],
    index: ChineseNameIndex,
) -> Hierarchy:
    def unit_view(level: int) -> dict[str, tuple[int, str, tuple[str, ...]]]:
        return {code: (unit.geoname_id, unit.name, unit.alternate_names) for code, unit in admin_units[level].items()}

    def unit_ids(level: int) -> dict[str, int]:
        return {code: unit.geoname_id for code, unit in admin_units[level].items()}

    return Hierarchy(
        admin1=translate_admin_codes(admin1_raw, index),
        admin2=translate_admin_codes(admin2_raw, index),
        admin3=translate_admin_units(unit_ids(3), unit_view(3), index),
        admin4=translate_admin_units(unit_ids(4), unit_view(4), index),
    )


def _write_levels(
    output: Path,
    *,
    cities500: Path,
    extra_file: Path,
    hierarchy: Hierarchy,
    index: ChineseNameIndex,
    overrides: NameOverrides,
    chain: ProviderChain,
    country_names: dict[str, str],
    min_population: int,
    stats: BuildStats,
) -> None:
    """写 ``geonameId -> 四级名称`` 映射表（full 超集，供所有变体共用）。"""
    written = 0
    fallback = 0
    count_country = stats.count_country
    with output.open("w", encoding="utf-8") as sink:
        for place in iter_output_places(
            cities500=cities500,
            extra_file=extra_file,
            min_population=min_population,
            full=True,
        ):
            names = resolve_place_names(place, hierarchy, index)
            names = chain.enrich(place, names)
            if not names.admin_1:
                names.admin_1 = index.get_country(place.country_code) or country_names.get(place.country_code, "")
            finalize_place_names(
                names,
                place.country_code,
                overrides,
                index.variant,
                fallback_name=(index.get(place.geoname_id) or place.name) if place.admin1_code else "",
            )
            if not names.admin_2:
                fallback += 1
            levels = names.levels()
            sink.write(
                "\t".join(
                    [
                        str(names.geoname_id),
                        levels["country"],
                        levels["admin_1"],
                        levels["admin_2"],
                        levels["admin_3"],
                        levels["admin_4"],
                    ]
                )
                + "\n"
            )
            count_country(place.country_code)
            written += 1
            if written % PROGRESS_EVERY == 0:
                logger.info("生成名称表：%d 条", written)
    stats.output_places = written
    stats.fallback_names = fallback
    logger.info("名称表完成：%d 条，其中 %d 条缺少二级行政名", written, fallback)


def _write_langs(source_dir: Path, options: BuildOptions) -> Path:
    """只写出旧版 Immich 实际读取的 ``en.json``，避免把整个语言包放进制品。"""
    destination = options.work_dir / "langs"
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    zh_path = source_dir / "zh.json"
    if not zh_path.exists():
        raise ParseError(f"缺少 {zh_path}")
    raw_countries = json.loads(zh_path.read_text(encoding="utf-8")).get("countries", {})
    countries = (
        {str(key): to_variant(str(value), options.chinese_variant) for key, value in raw_countries.items()}
        if isinstance(raw_countries, dict)
        else {}
    )
    (destination / "en.json").write_text(
        json.dumps({"locale": "en", "countries": countries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    license_source = source_dir.parent / "LICENSE"
    if not license_source.exists():
        raise ParseError(f"缺少 {license_source}，无法发布上游版权声明")
    shutil.copyfile(license_source, destination / "LICENSE")
    logger.info("语言文件写出完成：%d 个", len(list(destination.glob("*.json"))))
    return destination


# --------------------------------------------------------------------------
# 阶段 4：写出 geodata
# --------------------------------------------------------------------------


def iter_output_places(
    *,
    cities500: Path,
    extra_file: Path,
    min_population: int,
    full: bool,
) -> Iterator[Place]:
    """按变体过滤条件产出最终 cities500 的全部记录。"""
    yield from iter_places(cities500)
    for place in iter_places(extra_file):
        if full or place.population >= min_population or is_fine_grained(place):
            yield place


def iter_all_places(cities500: Path, extra_file: Path) -> Iterator[Place]:
    """provider 预取阶段使用：覆盖 full 与非 full 的并集。"""
    yield from iter_output_places(
        cities500=cities500,
        extra_file=extra_file,
        min_population=0,
        full=True,
    )


def is_fine_grained(place: Place) -> bool:
    return admin_code(place.country_code, place.admin1_code, place.admin2_code) in FINE_GRAINED_ADMIN2


def _emit_geodata(
    geodata_dir: Path,
    *,
    cities500: Path,
    paths: SourcePaths,
    extra_file: Path,
    admin1_raw: dict[str, AdminEntry],
    admin2_raw: dict[str, AdminEntry],
    country_rows: list[CountryInfoRow],
    hierarchy: Hierarchy,
    index: ChineseNameIndex,
    levels: dict[int, tuple[str, str, str, str, str]],
    pattern: str,
    full: bool,
    min_population: int,
    generated_at: str,
) -> None:
    geodata_dir.mkdir(parents=True, exist_ok=True)
    # 先写地点行，同时收集它们引用到的行政代码：上游代码表没收录、但地点行会引用的代码
    # 必须补进 adminN 表，否则 Immich 会把对应行的 admin1Name/admin2Name 写成 null。
    admin_areas: dict[tuple[int, str], str] = {}
    with (geodata_dir / "cities500.txt").open("w", encoding="utf-8") as sink:
        for place in iter_output_places(
            cities500=cities500,
            extra_file=extra_file,
            min_population=min_population,
            full=full,
        ):
            names = levels.get(place.geoname_id)
            name = display_name(names, pattern)
            if name:
                place = Place(columns=list(place.columns))
                place.columns[1] = name
                place.columns[2] = name
            sink.write(place.to_line() + "\n")
            _collect_place_admin_codes(place, names, admin_areas)

    # 港澳在 GeoNames 中以区/堂区作为 admin1，但 Immich 会把 admin1Name 当作"省/州"展示，
    # 因此文件里统一写特别行政区名称（区级信息仍保留在 place 层级的 admin_2/admin_3）。
    _write_admin_file(
        geodata_dir / "admin1CodesASCII.txt",
        admin1_raw,
        hierarchy.admin1,
        variant=index.variant,
        top_level_countries=tuple(SPECIAL_ADMIN_TOP_LEVEL),
        extra={code: name for (level, code), name in admin_areas.items() if level == 1},
    )
    _write_admin_file(
        geodata_dir / "admin2Codes.txt",
        admin2_raw,
        hierarchy.admin2,
        variant=index.variant,
        extra={code: name for (level, code), name in admin_areas.items() if level == 2},
    )
    _write_country_info(geodata_dir / "countryInfo.txt", country_rows, index, paths.langs_dir)
    shutil.copyfile(paths.geojson, geodata_dir / "ne_10m_admin_0_countries.geojson")
    (geodata_dir / "geodata-date.txt").write_text(generated_at + "\n", encoding="utf-8")
    (geodata_dir / "NOTICE.txt").write_text(GEODATA_NOTICE, encoding="utf-8")


def _collect_place_admin_codes(
    place: Place,
    names: tuple[str, str, str, str, str] | None,
    areas: dict[tuple[int, str], str],
) -> None:
    """把地点行引用到的行政代码收进 ``(level, code) -> name``。

    与规范数据集的 ``_collect_admin_areas`` 同口径：代码取自地点行，名称取自层级表，
    遇到空代码即停止（层级必须连续）。
    """
    if names is None:
        return
    code_parts = [place.country_code]
    codes = (place.admin1_code, place.admin2_code, place.admin3_code, place.admin4_code)
    for level, (code, name) in enumerate(zip(codes, names[1:], strict=True), start=1):
        if not code:
            return
        code_parts.append(code)
        if name:
            areas.setdefault((level, ".".join(code_parts)), name)


def _write_admin_file(
    path: Path,
    raw: dict[str, AdminEntry],
    translated: dict[str, str],
    *,
    variant: ChineseVariant,
    top_level_countries: tuple[str, ...] = (),
    extra: Mapping[str, str] | None = None,
) -> None:
    """写出 Immich 的 adminN 代码表。

    GeoNames 发布的代码表并不覆盖所有地点行用到的代码（例如德国州级市用 ``DE.03.00``，
    但 admin2Codes.txt 里没有这一条）。Immich 用 ``${country}.${admin1}[.${admin2}]``
    做键，缺条目会让这些行的 ``admin1Name`` / ``admin2Name`` 变成 null，按行政区名检索
    就会落空。因此除了上游代码表，还要补上地点行实际引用、且层级表能给出名称的代码。
    """

    def render(code: str, fallback: str) -> str:
        country = code.split(".")[0]
        if country in top_level_countries:
            return to_variant(SPECIAL_ADMIN_TOP_LEVEL[country], variant)
        return fallback

    written: set[str] = set()
    with path.open("w", encoding="utf-8") as sink:
        for code, entry in raw.items():
            name = render(code, translated.get(code) or to_variant(entry.name, variant))
            sink.write("\t".join([code, name, name, str(entry.geoname_id or "")]) + "\n")
            written.add(code)
        for code, fallback in sorted((extra or {}).items()):
            if code in written or not fallback:
                continue
            name = render(code, fallback)
            sink.write("\t".join([code, name, name, ""]) + "\n")


def _write_country_info(
    path: Path,
    rows: list[CountryInfoRow],
    index: ChineseNameIndex,
    langs_dir: Path,
) -> None:
    translations = _load_translations(langs_dir, index.variant)
    with path.open("w", encoding="utf-8") as sink:
        for row in rows:
            name = (
                index.get_country(row.alpha2)
                or translations.get(row.alpha2.upper())
                or to_variant(row.name, index.variant)
            )
            sink.write(row.with_name(name).to_line() + "\n")


def _load_translations(langs_dir: Path, variant: ChineseVariant = "hans") -> dict[str, str]:
    """读取 i18n-iso-countries 的 zh 语言包，并按目标字形转换。"""
    path = langs_dir / "zh.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    countries = payload.get("countries")
    if not isinstance(countries, dict):
        return {}
    return {str(k): to_variant(str(v), variant) for k, v in countries.items()}


def load_levels(path: Path) -> dict[int, tuple[str, str, str, str, str]]:
    """读取 ``levels.tsv``。

    同一份地名会在上百万行里反复出现，这里用字符串池复用对象：
    否则每个单元格都会创建独立字符串，峰值内存相差数百 MiB。
    """
    levels: dict[int, tuple[str, str, str, str, str]] = {}
    pool: dict[str, str] = {}
    reuse = pool.setdefault
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 6:
                continue
            levels[int(fields[0])] = (
                reuse(fields[1], fields[1]),
                reuse(fields[2], fields[2]),
                reuse(fields[3], fields[3]),
                reuse(fields[4], fields[4]),
                reuse(fields[5], fields[5]),
            )
    return levels


@lru_cache(maxsize=500_000)
def _render_levels(levels: tuple[str, str, str, str, str], pattern: str) -> str:
    """缓存重复行政层级的组合结果；真实数据约 27 个地点共享同一层级。"""
    country, admin_1, admin_2, admin_3, admin_4 = levels
    return compose(
        pattern,
        {
            "country": country,
            "admin_1": admin_1,
            "admin_2": admin_2,
            "admin_3": admin_3,
            "admin_4": admin_4,
        },
    )


def display_name(levels: tuple[str, str, str, str, str] | None, pattern: str) -> str:
    """按 pattern 组合一条名称记录。"""
    if levels is None:
        return ""
    return _render_levels(levels, pattern)


def write_pattern_rows(
    sink: TextIO,
    *,
    levels: dict[int, tuple[str, str, str, str, str]],
    patterns: tuple[str, ...],
) -> int:
    """把变体表写入任意文本流，避免调用方强制落一份明文中间文件。"""
    sink.write("\t".join(["geoname_id", *patterns]) + "\n")
    for geoname_id, values in levels.items():
        sink.write("\t".join([str(geoname_id), *(display_name(values, p) for p in patterns)]) + "\n")
    return len(levels)


def write_patterns_table(
    path: Path,
    *,
    levels_file: Path | None = None,
    levels: dict[int, tuple[str, str, str, str, str]] | None = None,
    patterns: tuple[str, ...],
) -> int:
    """生成 ``geonameId + 各变体展示名`` 表格，供容器运行时切换粒度。"""
    if levels is None:
        if levels_file is None:
            raise ParseError("write_patterns_table 需要 levels 或 levels_file")
        levels = load_levels(levels_file)
    with path.open("w", encoding="utf-8") as sink:
        return write_pattern_rows(sink, levels=levels, patterns=patterns)


__all__ = [
    "BuildResult",
    "display_name",
    "fetch_sources",
    "iter_output_places",
    "load_levels",
    "run_build",
    "write_pattern_rows",
    "write_patterns_table",
]
