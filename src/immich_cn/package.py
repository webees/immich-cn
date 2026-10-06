"""发布制品打包：各展示粒度 zip、校验和与 manifest。"""

from __future__ import annotations

import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from immich_cn.build import (
    BuildResult,
    cleanup_removable,
    display_name,
    iter_output_places,
    load_levels,
    write_pattern_rows,
    write_patterns_table,
)
from immich_cn.config import DEFAULT_PATTERN, BuildOptions
from immich_cn.errors import ParseError
from immich_cn.http import sha256_file
from immich_cn.logging_setup import get_logger
from immich_cn.models import Variant
from immich_cn.patterns import slugify, validate_pattern

logger = get_logger("package")

ZIP_COMPRESS_LEVEL = 6
GEODATA_PREFIX = "geodata/"


@dataclass(slots=True)
class PackageResult:
    """打包结果。"""

    dist_dir: Path
    artifacts: list[Path] = field(default_factory=list)
    variants: list[dict[str, object]] = field(default_factory=list)
    patterns_table: Path | None = None
    manifest: Path | None = None
    checksums: Path | None = None


def build_variants(patterns: tuple[str, ...]) -> list[Variant]:
    variants: list[Variant] = []
    for pattern in patterns:
        validate_pattern(pattern)
        slug = slugify(pattern)
        variants.append(Variant(pattern=pattern, slug=slug, full=False))
        variants.append(Variant(pattern=pattern, slug=slug, full=True))
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
                    "slug": variant.slug,
                    "full": variant.full,
                    "file": path.name,
                    "sizeBytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )

    default_slug = slugify(DEFAULT_PATTERN)
    _write_alias(options.dist_dir, "geodata.zip", f"geodata_{default_slug}.zip")
    _write_alias(options.dist_dir, "geodata_full.zip", f"geodata_{default_slug}_full.zip")

    legacy_zip = _write_i18n_archive(options.dist_dir, result)
    package_result.artifacts.append(legacy_zip)

    # 默认直接流式写 gzip，避免为 121 MiB 明文中间表额外写盘再读回。
    patterns_table = options.work_dir / "patterns.tsv"
    compressed = options.dist_dir / "patterns.tsv.gz"
    if options.keep_raw:
        rows = write_patterns_table(patterns_table, levels=levels, patterns=options.patterns)
        package_result.patterns_table = patterns_table
        compressed_patterns_table(patterns_table, compressed)
    else:
        rows = write_compressed_patterns_table(compressed, levels=levels, patterns=options.patterns)
        package_result.patterns_table = compressed
    package_result.artifacts.append(compressed)
    logger.info("变体表写出完成：%d 行 -> %s", rows, compressed.name)

    manifest = _write_manifest(options, result, package_result)
    package_result.manifest = manifest
    checksums = _write_checksums(options.dist_dir)
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
                sink.write((place.to_line() + "\n").encode("utf-8"))
        for source_name in (
            "admin1CodesASCII.txt",
            "admin2Codes.txt",
            "countryInfo.txt",
            "geodata-date.txt",
            "ne_10m_admin_0_countries.geojson",
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
    target = dist_dir / "i18n-iso-countries.zip"
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


def _write_alias(dist_dir: Path, alias: str, target: str) -> None:
    source = dist_dir / target
    if not source.exists():
        return
    destination = dist_dir / alias
    if destination.exists():
        destination.unlink()
    destination.hardlink_to(source)


def _write_manifest(options: BuildOptions, result: BuildResult, package_result: PackageResult) -> Path:
    manifest = result.as_manifest()
    manifest["variants"] = sorted(package_result.variants, key=lambda item: str(item["file"]))
    manifest["patternsTable"] = "patterns.tsv.gz"
    manifest["license"] = {
        "code": "MIT",
        "data": "见 NOTICE 与 docs/licensing.md",
    }
    path = options.dist_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_checksums(dist_dir: Path) -> Path:
    path = dist_dir / "SHA256SUMS"
    entries: list[tuple[str, str]] = []
    for item in sorted(dist_dir.iterdir()):
        if not item.is_file() or item.name in {"SHA256SUMS"}:
            continue
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
