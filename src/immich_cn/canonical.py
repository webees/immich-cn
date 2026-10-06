"""规范数据集导出。

规范数据集是本项目自己的主数据格式：SQLite 中的地点、行政层级、国家、来源与统计
可以直接被 SQLite、DuckDB、BI 工具或其他程序消费。Immich 文本目录只是为既有
消费者提供的适配器，不再决定内部模型。
"""

from __future__ import annotations

import json
import math
import sqlite3
import zipfile
from collections.abc import Mapping
from pathlib import Path

from immich_cn.build import BuildResult, is_fine_grained
from immich_cn.errors import ParseError
from immich_cn.geonames import iter_places
from immich_cn.logging_setup import get_logger
from immich_cn.models import Place

logger = get_logger("canonical")

DATASET_SCHEMA_VERSION = 1
DATASET_FORMAT = "immich-cn.dataset/1"
DATASET_ARCHIVE = "dataset.sqlite.zip"
SQLITE_MEMBER = "dataset.sqlite"
SCHEMA_MEMBER = "schema.json"
NOTICE_MEMBER = "NOTICE.txt"
README_MEMBER = "README.txt"

_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_ZIP_COMPRESS_LEVEL = 6


def write_canonical_dataset(
    *,
    dist_dir: Path,
    work_dir: Path,
    result: BuildResult,
    levels: Mapping[int, tuple[str, str, str, str, str]],
    min_population: int,
) -> Path:
    """生成可查询的规范数据集归档 ``dataset.sqlite.zip``。"""
    dist_dir.mkdir(parents=True, exist_ok=True)
    database = work_dir / "dataset.sqlite"
    database.unlink(missing_ok=True)
    try:
        _create_database(
            database,
            result=result,
            levels=levels,
            min_population=min_population,
        )
        target = dist_dir / DATASET_ARCHIVE
        with zipfile.ZipFile(
            target,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=_ZIP_COMPRESS_LEVEL,
        ) as archive:
            _write_file(archive, database, SQLITE_MEMBER)
            _write_bytes(archive, SCHEMA_MEMBER, _schema_payload())
            _write_file(archive, result.geodata_dir / "NOTICE.txt", NOTICE_MEMBER)
            _write_bytes(archive, README_MEMBER, _readme_payload())
    finally:
        database.unlink(missing_ok=True)
    logger.info("规范数据集写出完成：%s", target.name)
    return target


def _create_database(
    path: Path,
    *,
    result: BuildResult,
    levels: Mapping[int, tuple[str, str, str, str, str]],
    min_population: int,
) -> None:
    places = _load_places(result)
    countries = _load_countries(result.geodata_dir / "countryInfo.txt")
    admin_areas = _collect_admin_areas(places, levels)

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA page_size = 4096")
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA temp_store = MEMORY")
        _create_schema(connection)
        _insert_metadata(connection, result=result, place_count=len(places))
        connection.executemany(
            "INSERT INTO sources(name, url, sha256, size_bytes, etag, last_modified) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    source.name,
                    source.url,
                    source.sha256,
                    source.size_bytes,
                    source.etag,
                    source.last_modified,
                )
                for source in sorted(result.sources, key=lambda item: item.name)
            ],
        )
        connection.executemany(
            "INSERT INTO countries(code, name, iso3, iso_numeric, geoname_id) VALUES (?, ?, ?, ?, ?)",
            [
                (code, row["name"], row["iso3"], row["isoNumeric"], row["geonameId"])
                for code, row in sorted(countries.items())
            ],
        )
        connection.executemany(
            "INSERT INTO admin_areas(level, code, name) VALUES (?, ?, ?)",
            [(level, code, name) for (level, code), name in sorted(admin_areas.items())],
        )
        connection.executemany(
            """
            INSERT INTO places(
                geoname_id, name, ascii_name, country_code, latitude, longitude, population,
                feature_class, feature_code, admin1_code, admin2_code, admin3_code, admin4_code,
                source, in_default
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    place.geoname_id,
                    place.name,
                    place.ascii_name,
                    place.country_code,
                    _coordinate(place, 4),
                    _coordinate(place, 5),
                    place.population,
                    place.feature_class,
                    place.feature_code,
                    place.admin1_code,
                    place.admin2_code,
                    place.admin3_code,
                    place.admin4_code,
                    source_name,
                    int(source_name == "cities500" or place.population >= min_population or is_fine_grained(place)),
                )
                for place, source_name in places
            ],
        )
        connection.executemany(
            "INSERT INTO place_names(geoname_id, country, admin1, admin2, admin3, admin4) VALUES (?, ?, ?, ?, ?, ?)",
            [(place.geoname_id, *levels.get(place.geoname_id, ("", "", "", "", ""))) for place, _ in places],
        )
        connection.commit()
        connection.execute("VACUUM")
    except sqlite3.Error as error:
        raise ParseError(f"规范数据集写入失败：{error}") from error
    finally:
        connection.close()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE dataset_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE sources (
            name TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
            etag TEXT,
            last_modified TEXT
        );
        CREATE TABLE countries (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            iso3 TEXT NOT NULL,
            iso_numeric TEXT NOT NULL,
            geoname_id INTEGER
        );
        CREATE TABLE admin_areas (
            level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 4),
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (level, code)
        );
        CREATE TABLE places (
            geoname_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            ascii_name TEXT NOT NULL,
            country_code TEXT NOT NULL,
            latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
            longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
            population INTEGER NOT NULL CHECK (population >= 0),
            feature_class TEXT NOT NULL,
            feature_code TEXT NOT NULL,
            admin1_code TEXT NOT NULL,
            admin2_code TEXT NOT NULL,
            admin3_code TEXT NOT NULL,
            admin4_code TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('cities500', 'extra')),
            in_default INTEGER NOT NULL CHECK (in_default IN (0, 1))
        );
        CREATE TABLE place_names (
            geoname_id INTEGER PRIMARY KEY REFERENCES places(geoname_id),
            country TEXT NOT NULL,
            admin1 TEXT NOT NULL,
            admin2 TEXT NOT NULL,
            admin3 TEXT NOT NULL,
            admin4 TEXT NOT NULL
        );
        CREATE INDEX places_country_admin ON places(country_code, admin1_code, admin2_code);
        CREATE INDEX places_location ON places(latitude, longitude);
        CREATE VIEW localized_places AS
        SELECT
            p.geoname_id,
            p.name AS source_name,
            p.ascii_name,
            p.country_code,
            COALESCE(NULLIF(c.name, ''), n.country) AS country_name,
            p.admin1_code,
            n.admin1 AS admin1_name,
            p.admin2_code,
            n.admin2 AS admin2_name,
            p.admin3_code,
            n.admin3 AS admin3_name,
            p.admin4_code,
            n.admin4 AS admin4_name,
            p.latitude,
            p.longitude,
            p.population,
            p.feature_class,
            p.feature_code,
            p.in_default
        FROM places AS p
        JOIN place_names AS n USING (geoname_id)
        LEFT JOIN countries AS c ON c.code = p.country_code;
        """
    )


def _insert_metadata(connection: sqlite3.Connection, *, result: BuildResult, place_count: int) -> None:
    config = result.build_config
    metadata = {
        "format": DATASET_FORMAT,
        "schemaVersion": str(DATASET_SCHEMA_VERSION),
        "generatedAt": result.generated_at,
        "toolVersion": str(result.as_manifest()["tool"]["version"]),  # type: ignore[index]
        "buildRevision": result.build_revision,
        "provider": str(config.get("provider", "")),
        "chineseVariant": str(config.get("chineseVariant", "")),
        "placeCount": str(place_count),
    }
    connection.executemany(
        "INSERT INTO dataset_meta(key, value) VALUES (?, ?)",
        sorted(metadata.items()),
    )


def _load_places(result: BuildResult) -> list[tuple[Place, str]]:
    rows = [(place, "cities500") for place in iter_places(result.cities500)]
    rows.extend((place, "extra") for place in iter_places(result.extra_file))
    rows.sort(key=lambda item: item[0].geoname_id)
    return rows


def _load_countries(path: Path) -> dict[str, dict[str, object]]:
    countries: dict[str, dict[str, object]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 17:
                continue
            geoname_id = int(fields[16]) if fields[16].isdigit() else None
            countries[fields[0]] = {
                "name": fields[4],
                "iso3": fields[1],
                "isoNumeric": fields[2],
                "geonameId": geoname_id,
            }
    return countries


def _collect_admin_areas(
    places: list[tuple[Place, str]],
    levels: Mapping[int, tuple[str, str, str, str, str]],
) -> dict[tuple[int, str], str]:
    areas: dict[tuple[int, str], str] = {}
    for place, _ in places:
        names = levels.get(place.geoname_id)
        if names is None:
            continue
        country = place.country_code
        codes = (place.admin1_code, place.admin2_code, place.admin3_code, place.admin4_code)
        name_values = names[1:]
        code_parts: list[str] = [country]
        for level, (code, name) in enumerate(zip(codes, name_values, strict=True), start=1):
            if not code:
                break
            code_parts.append(code)
            if name:
                areas.setdefault((level, ".".join(code_parts)), name)
    return areas


def _coordinate(place: Place, index: int) -> float:
    value = float(place.columns[index])
    if not math.isfinite(value):
        raise ParseError(f"GeoNames {place.geoname_id} 的坐标不是有限值：{value!r}")
    return value


def _schema_payload() -> bytes:
    payload = {
        "format": DATASET_FORMAT,
        "schemaVersion": DATASET_SCHEMA_VERSION,
        "storage": {"engine": "sqlite", "file": SQLITE_MEMBER},
        "primaryTables": {
            "places": "规范地点记录；一条记录对应一个 GeoNames ID",
            "place_names": "地点到国家及四级行政名的中文映射",
            "admin_areas": "可从地点记录推导的行政层级名称",
            "countries": "国家代码、名称与 GeoNames 元数据",
            "sources": "本次构建使用的上游文件及其 SHA256",
            "dataset_meta": "格式版本、构建工具、provider 与统计元数据",
        },
        "views": {"localized_places": "places 与 place_names 的联合查询视图"},
        "compatibility": {
            "immich": "通过 geodata*.zip 适配器导出；Immich 文本格式不属于本规范",
        },
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _readme_payload() -> bytes:
    return (
        "immich-cn canonical dataset\n"
        "===========================\n\n"
        "dataset.sqlite 是可查询的 SQLite 3 数据库，不是 Immich 文本格式。\n"
        "示例：\n"
        '  sqlite3 dataset.sqlite "SELECT country_name, admin1_name, admin2_name, source_name '
        'FROM localized_places WHERE geoname_id = 1816670;"\n\n'
        "Immich 兼容输出请使用同目录的 geodata*.zip。\n"
    ).encode()


def _write_file(archive: zipfile.ZipFile, source: Path, arcname: str) -> None:
    info = zipfile.ZipInfo(arcname, date_time=_ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with source.open("rb") as handle, archive.open(info, "w", force_zip64=True) as sink:
        while chunk := handle.read(1024 * 1024):
            sink.write(chunk)


def _write_bytes(archive: zipfile.ZipFile, arcname: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(arcname, date_time=_ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, payload)
