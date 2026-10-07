"""发布制品打包：各展示粒度 zip、校验和与 manifest。"""

from __future__ import annotations

import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from immich_cn import ARTIFACT_SPEC_VERSION
from immich_cn.artifact_spec import (
    CHECKSUMS_FILE,
    DATASET_FILE,
    I18N_FILE,
    MANIFEST_FILE,
    PATTERNS_FILE,
    artifact_id,
    canonical_filename,
)
from immich_cn.dataset import DATASET_ARCHIVE, DATASET_FORMAT, DATASET_SCHEMA_VERSION, write_canonical_dataset
from immich_cn.display import validate_pattern
from immich_cn.domain import Variant
from immich_cn.errors import ParseError, VerifyError
from immich_cn.fetching import sha256_file
from immich_cn.localization import CHINESE_OUTPUT_REGIONS, has_cjk
from immich_cn.logging_config import get_logger
from immich_cn.pipeline import (
    BuildResult,
    cleanup_removable,
    display_name,
    iter_output_places,
    load_levels,
    write_pattern_rows,
    write_patterns_table,
)
from immich_cn.settings import BuildOptions

logger = get_logger("package")

ZIP_COMPRESS_LEVEL = 6
GEODATA_PREFIX = "geodata/"


@dataclass(slots=True)
class PackageResult:
    """打包结果。"""

    dist_dir: Path
    artifacts: list[Path] = field(default_factory=list)
    variants: list[dict[str, object]] = field(default_factory=list)
    dataset: Path | None = None
    checksums: Path | None = None


def build_variants(patterns: tuple[str, ...]) -> list[Variant]:
    variants: list[Variant] = []
    for pattern in patterns:
        validate_pattern(pattern)
        variants.append(Variant(pattern=pattern, full=False))
        variants.append(Variant(pattern=pattern, full=True))
    return variants


def package_all(options: BuildOptions, result: BuildResult) -> PackageResult:
    """生成全部发布制品。"""
    options.dist_dir.mkdir(parents=True, exist_ok=True)
    levels = load_levels(result.names_file)
    variants = build_variants(options.patterns)

    logger.info("开始打包 %d 个变体", len(variants))
    workers = max(1, min(options.jobs, 4, len(variants)))
    package_result = PackageResult(dist_dir=options.dist_dir)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="zip") as pool:
        futures = {
            pool.submit(
                _write_variant,
                options=options,
                result=result,
                variant=variant,
                levels=levels,
            ): variant
            for variant in variants
        }
        for future, variant in futures.items():
            path = future.result()
            package_result.artifacts.append(path)
            package_result.variants.append(
                {
                    "pattern": variant.pattern,
                    "full": variant.full,
                    "file": path.name,
                    "id": artifact_id(variant.pattern, variant.full),
                    "profile": variant.profile,
                    "scope": variant.scope,
                    "schemaVersion": 1,
                    "canonicalFile": canonical_filename(variant.pattern, variant.full),
                    "sizeBytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )

    legacy_zip = _write_i18n_archive(options.dist_dir, result)
    package_result.artifacts.append(legacy_zip)

    # 默认直接流式写 gzip，避免为 121 MiB 明文中间表额外写盘再读回。
    patterns_table = options.work_dir / "immich-cn-patterns-v1.tsv"
    compressed = options.dist_dir / PATTERNS_FILE
    if options.keep_raw:
        rows = write_patterns_table(patterns_table, levels=levels, patterns=options.patterns)
        compressed_patterns_table(patterns_table, compressed)
    else:
        rows = write_compressed_patterns_table(compressed, levels=levels, patterns=options.patterns)
    package_result.artifacts.append(compressed)
    logger.info("变体表写出完成：%d 行 -> %s", rows, compressed.name)

    package_result.dataset = write_canonical_dataset(
        dist_dir=options.dist_dir,
        work_dir=options.work_dir,
        result=result,
        levels=levels,
        min_population=options.min_population,
    )
    package_result.artifacts.append(package_result.dataset)

    manifest = _write_manifest(options, result, package_result)
    checksums = _write_checksums(options.dist_dir, [*package_result.artifacts, manifest])
    package_result.checksums = checksums
    if not options.keep_raw:
        cleanup_removable(result, work_dir=options.work_dir)
    logger.info("打包完成，共 %d 个制品", len(package_result.artifacts))
    return package_result


def _write_variant(
    *,
    options: BuildOptions,
    result: BuildResult,
    variant: Variant,
    levels: dict[int, tuple[str, str, str, str, str]],
) -> Path:
    target = options.dist_dir / variant.filename
    logger.info("打包 %s", target.name)
    date_time = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=ZIP_COMPRESS_LEVEL) as archive:
        info = zipfile.ZipInfo(f"{GEODATA_PREFIX}cities500.txt", date_time=date_time)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        with archive.open(info, "w", force_zip64=True) as sink:
            untranslated = 0
            untranslated_samples: list[str] = []
            for place in iter_output_places(
                cities500=result.cities500,
                extra_file=result.extra_file,
                min_population=options.min_population,
                full=variant.full,
            ):
                name = display_name(levels.get(place.geoname_id), variant.pattern)
                if name:
                    place = type(place)(columns=list(place.columns))
                    place.columns[1] = name
                    place.columns[2] = name
                # 上游缺中文别名时会把英文原名透传；这类值会让 {admin_3}/{admin_4} 变体
                # 显示英文地名（2026-10-07 实测 7~8 行），必须在打包阶段拦下而不是发布。
                if place.country_code in CHINESE_OUTPUT_REGIONS and not has_cjk(place.columns[1]):
                    untranslated += 1
                    if len(untranslated_samples) < 5:
                        untranslated_samples.append(f"{place.country_code}:{place.geoname_id}={place.columns[1]}")
                sink.write((place.to_line() + "\n").encode("utf-8"))
            if untranslated:
                raise VerifyError(
                    f"{variant.filename} 有 {untranslated} 条中文地区记录的展示名不含中文"
                    f"（pattern={variant.pattern}，样例：{'、'.join(untranslated_samples)}）"
                    "：请补 config/overrides.toml 的 [admins]，"
                    "或修正该层级名称的中文来源"
                )
        for source_name in (
            "admin1CodesASCII.txt",
            "admin2Codes.txt",
            "countryInfo.txt",
            "geodata-date.txt",
            "ne_10m_admin_0_countries.geojson",
            "NOTICE.txt",
        ):
            _zip_file(archive, result.geodata_dir / source_name, f"{GEODATA_PREFIX}{source_name}", date_time)
        _zip_bytes(
            archive,
            f"{GEODATA_PREFIX}build-info.json",
            json.dumps(
                {
                    "variant": {"pattern": variant.pattern, "full": variant.full},
                    "generatedAt": result.generated_at,
                    "stats": result.stats.as_dict(),
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
            date_time,
        )
    return target


ZipDate = tuple[int, int, int, int, int, int]


def _zip_file(archive: zipfile.ZipFile, source: Path, arcname: str, date_time: ZipDate) -> None:
    if not source.exists():
        return
    info = zipfile.ZipInfo(arcname, date_time=date_time)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with source.open("rb") as handle, archive.open(info, "w", force_zip64=True) as sink:
        while chunk := handle.read(1024 * 1024):
            sink.write(chunk)


def _zip_bytes(
    archive: zipfile.ZipFile,
    arcname: str,
    payload: bytes,
    date_time: ZipDate,
) -> None:
    info = zipfile.ZipInfo(arcname, date_time=date_time)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, payload)


def _write_i18n_archive(dist_dir: Path, result: BuildResult) -> Path:
    target = dist_dir / I18N_FILE
    license_path = result.langs_dir / "LICENSE"
    if not license_path.exists():
        raise ParseError(f"缺少 {license_path}，拒绝生成不含版权声明的语言包")
    logger.info("打包 %s", target.name)
    date_time = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=ZIP_COMPRESS_LEVEL) as archive:
        _zip_file(archive, license_path, "LICENSE", date_time)
        for json_file in sorted(result.langs_dir.glob("*.json")):
            _zip_file(archive, json_file, f"langs/{json_file.name}", date_time)
    return target


def _asset_kind(name: str) -> str:
    if name.startswith("immich-cn-geodata-"):
        return "geodata"
    if name == DATASET_FILE:
        return "dataset"
    if name == PATTERNS_FILE:
        return "patterns"
    if name == I18N_FILE:
        return "i18n"
    return "other"


def _write_manifest(options: BuildOptions, result: BuildResult, package_result: PackageResult) -> Path:
    manifest = result.as_manifest()
    manifest["artifactSpecVersion"] = ARTIFACT_SPEC_VERSION
    manifest["artifacts"] = sorted(package_result.variants, key=lambda item: str(item["id"]))
    manifest["assets"] = [
        {
            "file": path.name,
            "kind": _asset_kind(path.name),
            "sizeBytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(package_result.artifacts, key=lambda item: item.name)
    ]
    manifest["patternsTable"] = PATTERNS_FILE
    if package_result.dataset is not None:
        manifest["dataset"] = {
            "file": DATASET_ARCHIVE,
            "format": DATASET_FORMAT,
            "schemaVersion": DATASET_SCHEMA_VERSION,
            "sizeBytes": package_result.dataset.stat().st_size,
            "sha256": sha256_file(package_result.dataset),
        }
    manifest["license"] = {
        "code": "MIT",
        "data": "见 NOTICE 与 docs/licensing.md",
    }
    path = options.dist_dir / MANIFEST_FILE
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_checksums(dist_dir: Path, files: list[Path]) -> Path:
    """只登记本次构建产出的文件。

    不能扫描 `dist_dir`：历史残留（旧命名、临时文件）会被一起写进校验和，
    而发布路径是 `dist/*`，于是残留文件会被签名并上传。
    """
    path = dist_dir / CHECKSUMS_FILE
    entries: list[tuple[str, str]] = []
    for item in sorted({item for item in files if item.name != CHECKSUMS_FILE}, key=lambda item: item.name):
        if not item.is_file():
            raise FileNotFoundError(f"待登记制品不存在：{item}")
        entries.append((sha256_file(item), item.name))
    path.write_text("".join(f"{digest}  {name}\n" for digest, name in entries), encoding="utf-8")
    return path


def compressed_patterns_table(source: Path, destination: Path) -> Path:
    """把变体表压缩为 gzip，供容器镜像使用。"""
    import gzip

    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, gzip.open(destination, "wb", compresslevel=6) as dst:
        while chunk := src.read(1024 * 1024):
            dst.write(chunk)
    return destination


def write_compressed_patterns_table(
    destination: Path,
    *,
    levels: dict[int, tuple[str, str, str, str, str]],
    patterns: tuple[str, ...],
) -> int:
    """直接从名称表写出 gzip，避免落一份百 MiB 级明文中间文件。"""
    import gzip

    destination.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(destination, "wt", encoding="utf-8", newline="\n", compresslevel=6) as sink:
        return write_pattern_rows(sink, levels=levels, patterns=patterns)
