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
import shutil
import tarfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from immich_cn import SCHEMA_VERSION, __version__
from immich_cn.chinese import ChineseNameIndex, NameOverrides, build_name_index, to_variant
from immich_cn.config import (
    DEFAULT_PATTERN,
    FINE_GRAINED_ADMIN2,
    BuildOptions,
    SourceSpec,
    geonames_sources,
    i18n_sources,
    natural_earth_source,
)
from immich_cn.errors import ImmichCnError, ParseError
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
)
from immich_cn.hierarchy import (
    Hierarchy,
    finalize_place_names,
    resolve_place_names,
    translate_admin_codes,
    translate_admin_units,
)
from immich_cn.http import FetchedSource, Fetcher
from immich_cn.logging_setup import get_logger
from immich_cn.models import AdminEntry, BuildStats, Place, SourceRecord
from immich_cn.patterns import compose, validate_pattern
from immich_cn.providers import ProviderChain, build_chain

logger = get_logger("build")

PROGRESS_EVERY = 500_000

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
    provider_names: list[str] = field(default_factory=list)
    index_stats: dict[str, int] = field(default_factory=dict)
    admin_entries: dict[str, int] = field(default_factory=dict)
    build_config: dict[str, object] = field(default_factory=dict)

    def as_manifest(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "tool": {"name": "immich-cn", "version": __version__},
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


def run_build(options: BuildOptions) -> BuildResult:
    """执行完整构建，返回产物路径与统计。"""
    for pattern in options.patterns:
        validate_pattern(pattern)
    options.ensure_dirs()

    records = [] if options.skip_fetch else fetch_sources(options)
    paths = _source_paths(options)
    overrides = NameOverrides.load(options.config_dir / "overrides.toml")

    stats = BuildStats()
    admin1_raw = read_admin_codes(paths.admin1)
    admin2_raw = read_admin_codes(paths.admin2)
    country_rows = read_country_info(paths.country_info)

    admin_units = build_admin_units(paths.country_dumps)
    stats.admin3_entries = len(admin_units[3])
    stats.admin4_entries = len(admin_units[4])

    cities500_file = options.work_dir / "cities500.txt"
    existing_ids, existing_locations = _prepare_cities500(paths.cities500, cities500_file, admin1_raw)
    stats.source_places = len(existing_ids)
    logger.info("cities500 有效记录：%d 条", stats.source_places)

    extra_file = options.work_dir / "extra_all.txt"
    extra_ids = _select_extra_places(
        paths.country_dumps,
        extra_file,
        admin1_raw=admin1_raw,
        existing_ids=existing_ids,
        existing_locations=existing_locations,
    )
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
            min_population=options.min_population,
            stats=stats,
        )
    finally:
        chain.close()

    langs_dir = _write_langs(paths.langs_dir, options)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
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
    if (destination / "langs" / "zh.json").exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        files = [member for member in tar.getmembers() if member.name.startswith("package/langs/") and member.isfile()]
        if not files:
            raise ParseError(f"{archive.name} 中未找到 package/langs/ 目录")
        for member in files:
            target = destination / member.name.removeprefix("package/")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            with source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
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


def cleanup_removable(result: BuildResult) -> int:
    """删除不再需要的中间文件，返回释放的字节数。"""
    freed = 0
    for path in result.removable_paths:
        try:
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
) -> tuple[set[int], set[tuple[str, str]]]:
    """过滤 cities500 并落盘为 canonical 版本，后续阶段只读这一份。"""
    ids: set[int] = set()
    locations: set[tuple[str, str]] = set()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as sink:
        for count, place in enumerate(iter_places(path), start=1):
            if not keep_place(place, admin1_raw):
                continue
            ids.add(place.geoname_id)
            locations.add(place.location_key)
            sink.write(place.to_line() + "\n")
            if count % PROGRESS_EVERY == 0:
                logger.info("扫描 cities500：%d 行", count)
    return ids, locations


def _select_extra_places(
    country_dumps: tuple[Path, ...],
    output: Path,
    *,
    admin1_raw: dict[str, AdminEntry],
    existing_ids: set[int],
    existing_locations: set[tuple[str, str]],
) -> set[int]:
    """把国家全量 dump 中不在 cities500 的记录写入 ``extra_all.txt``。

    这里保留全部候选，是否进入非 full 变体留到打包阶段按人口过滤，
    因此每个国家 dump 只需要扫描一次。
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    ids: set[int] = set()
    count = 0
    with output.open("w", encoding="utf-8") as sink:
        for path in country_dumps:
            if not path.exists():
                logger.warning("缺少国家 dump %s，已跳过", path)
                continue
            for place in iter_places(path):
                if not keep_place(place, admin1_raw):
                    continue
                if place.geoname_id in existing_ids or place.location_key in existing_locations:
                    continue
                existing_locations.add(place.location_key)
                ids.add(place.geoname_id)
                sink.write(place.to_line() + "\n")
                count += 1
                if count % PROGRESS_EVERY == 0:
                    logger.info("筛选额外地点：%d 条", count)
    logger.info("额外地点候选：%d 条", count)
    return ids


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
    for record in iter_alternate_names(path, wanted):
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
    min_population: int,
    stats: BuildStats,
) -> None:
    """写 ``geonameId -> 四级名称`` 映射表（full 超集，供所有变体共用）。"""
    written = 0
    fallback = 0
    with output.open("w", encoding="utf-8") as sink:
        for place in iter_output_places(
            cities500=cities500,
            extra_file=extra_file,
            min_population=min_population,
            full=True,
        ):
            names = resolve_place_names(place, hierarchy, index)
            names = chain.enrich(place, names)
            finalize_place_names(names, place.country_code, overrides)
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
            written += 1
            if written % PROGRESS_EVERY == 0:
                logger.info("生成名称表：%d 条", written)
    stats.output_places = written
    stats.fallback_names = fallback
    logger.info("名称表完成：%d 条，其中 %d 条缺少二级行政名", written, fallback)


def _write_langs(source_dir: Path, options: BuildOptions) -> Path:
    """把 zh 语言文件写成 ``en.json``，兼容只读取 en 的旧版 Immich。"""
    destination = options.work_dir / "langs"
    destination.mkdir(parents=True, exist_ok=True)
    zh_path = source_dir / "zh.json"
    if not zh_path.exists():
        raise ParseError(f"缺少 {zh_path}")
    countries = json.loads(zh_path.read_text(encoding="utf-8")).get("countries", {})
    for json_file in sorted(source_dir.glob("*.json")):
        target = destination / json_file.name
        payload = json.loads(json_file.read_text(encoding="utf-8"))
        if json_file.name == "en.json":
            payload = {"locale": "en", "countries": countries}
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    _write_admin_file(geodata_dir / "admin1CodesASCII.txt", admin1_raw, hierarchy.admin1)
    _write_admin_file(geodata_dir / "admin2Codes.txt", admin2_raw, hierarchy.admin2)
    _write_country_info(geodata_dir / "countryInfo.txt", country_rows, index, paths.langs_dir)
    shutil.copyfile(paths.geojson, geodata_dir / "ne_10m_admin_0_countries.geojson")
    (geodata_dir / "geodata-date.txt").write_text(generated_at + "\n", encoding="utf-8")

    with (geodata_dir / "cities500.txt").open("w", encoding="utf-8") as sink:
        for place in iter_output_places(
            cities500=cities500,
            extra_file=extra_file,
            min_population=min_population,
            full=full,
        ):
            name = display_name(levels.get(place.geoname_id), pattern)
            if name:
                place = Place(columns=list(place.columns))
                place.columns[1] = name
                place.columns[2] = name
            sink.write(place.to_line() + "\n")


def _write_admin_file(path: Path, raw: dict[str, AdminEntry], translated: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8") as sink:
        for code, entry in raw.items():
            name = translated.get(code) or to_variant(entry.name)
            sink.write("\t".join([code, name, name, str(entry.geoname_id or "")]) + "\n")


def _write_country_info(
    path: Path,
    rows: list[CountryInfoRow],
    index: ChineseNameIndex,
    langs_dir: Path,
) -> None:
    translations = _load_translations(langs_dir)
    with path.open("w", encoding="utf-8") as sink:
        for row in rows:
            name = (
                index.get_country(row.alpha2)
                or translations.get(row.alpha2.upper())
                or to_variant(row.name, index.variant)
            )
            sink.write(row.with_name(name).to_line() + "\n")


def _load_translations(langs_dir: Path) -> dict[str, str]:
    path = langs_dir / "zh.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    countries = payload.get("countries")
    return {str(k): str(v) for k, v in countries.items()} if isinstance(countries, dict) else {}


def load_levels(path: Path) -> dict[int, tuple[str, str, str, str, str]]:
    """读取 ``levels.tsv``。"""
    levels: dict[int, tuple[str, str, str, str, str]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 6:
                continue
            levels[int(fields[0])] = (fields[1], fields[2], fields[3], fields[4], fields[5])
    return levels


def display_name(levels: tuple[str, str, str, str, str] | None, pattern: str) -> str:
    """按 pattern 组合一条名称记录。"""
    if levels is None:
        return ""
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
        sink.write("\t".join(["geoname_id", *patterns]) + "\n")
        for geoname_id, values in levels.items():
            sink.write("\t".join([str(geoname_id), *(display_name(values, p) for p in patterns)]) + "\n")
    return len(levels)


__all__ = [
    "BuildResult",
    "SourcePaths",
    "display_name",
    "fetch_sources",
    "is_fine_grained",
    "iter_all_places",
    "iter_output_places",
    "keep_place",
    "load_levels",
    "run_build",
    "write_patterns_table",
]
