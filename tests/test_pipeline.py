from __future__ import annotations

import gzip
import io
import json
import sqlite3
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from immich_cn import __version__
from immich_cn.errors import ParseError
from immich_cn.packaging import build_variants, package_all
from immich_cn.pipeline import (
    _alternate_stream,
    _extract_i18n,
    cleanup_removable,
    iter_output_places,
    load_levels,
    run_build,
    write_patterns_table,
)
from immich_cn.settings import BuildOptions
from immich_cn.validation import assert_valid, verify_geodata
from tests.synthetic import create_synthetic_sources, geo_row, write_lines


def test_end_to_end_build(build_options: BuildOptions) -> None:
    result = run_build(build_options)

    geodata = result.geodata_dir
    for name in (
        "admin1CodesASCII.txt",
        "admin2Codes.txt",
        "cities500.txt",
        "countryInfo.txt",
        "geodata-date.txt",
        "ne_10m_admin_0_countries.geojson",
    ):
        assert (geodata / name).exists(), name

    cities = (geodata / "cities500.txt").read_text(encoding="utf-8").splitlines()
    rows = {line.split("\t")[0]: line.split("\t") for line in cities}
    assert "9999999" not in rows, "缺少有效 admin1 的记录应被过滤"
    assert rows["1886760"][1] == "苏州市"
    assert rows["1816670"][1] == "北京市"
    assert rows["1819729"][1] == "元朗区"
    assert rows["1668341"][1] == "台北市"
    assert rows["1880252"][1] == "新加坡"

    # 非 full 变体：人口为 0 的补充点位不写入 geodata 目录
    assert "9101" not in rows
    assert "9100" in rows
    # 与 cities500 重复的记录（同 ID 或同坐标）必须只出现一次
    ids = [line.split("\t")[0] for line in cities]
    assert ids.count("1886760") == 1
    assert "9200" not in rows

    admin1 = (geodata / "admin1CodesASCII.txt").read_text(encoding="utf-8")
    assert "江苏省" in admin1
    # 港澳的 admin1 必须是特别行政区名称（区级信息走 place 层级的 admin_2/admin_3）
    assert "HK.NYL\t香港特别行政区\t" in admin1
    assert "MO.11875154\t澳门特别行政区\t" in admin1
    country_info = (geodata / "countryInfo.txt").read_text(encoding="utf-8")
    assert "\t中国\t" in country_info
    country_rows = {line.split("\t")[0]: line.split("\t") for line in country_info.splitlines()}
    assert country_rows["CS"][4] == "塞尔维亚和黑山"
    assert country_rows["AN"][4] == "荷属安的列斯"

    levels = load_levels(result.names_file)
    # 元组顺序为 (country, admin_1, admin_2, admin_3, admin_4)
    assert levels[9100][2] == "苏州市"
    assert levels[9100][3] == "昆山市"
    assert levels[9100][4] == "周市镇"

    results = verify_geodata(geodata)
    assert_valid(results)


def test_alternate_stream_keeps_chinese_and_japanese_languages(tmp_path: Path) -> None:
    path = tmp_path / "alternateNamesV2.txt"
    write_lines(
        path,
        [
            "1\t10\ten\tEnglish\t1\t0\t0\t0",
            "2\t10\tjam\tJamaican\t1\t0\t0\t0",
            "3\t10\tzh-Hant\t臺北\t0\t0\t0\t0",
            "4\t10\tja\t東京\t1\t0\t0\t0",
            "5\t10\tJA\t大阪\t0\t0\t0\t0",
            "6\t11\tja\t別府\t1\t0\t0\t0",
        ],
    )
    assert list(_alternate_stream(path, {10})) == [
        (10, "zh-Hant", "臺北", False, False),
        (10, "ja", "東京", True, False),
        (10, "JA", "大阪", False, False),
    ]


def test_build_is_idempotent(build_options: BuildOptions) -> None:
    first = run_build(build_options)
    second = run_build(build_options)
    assert first.stats.output_places == second.stats.output_places
    assert (second.geodata_dir / "cities500.txt").read_text(encoding="utf-8") == (
        first.geodata_dir / "cities500.txt"
    ).read_text(encoding="utf-8")


def test_manifest_records_ci_build_revision(build_options: BuildOptions, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    manifest = run_build(build_options).as_manifest()
    assert manifest["tool"] == {"name": "immich-cn", "version": __version__, "revision": "deadbeef"}


def test_package_produces_expected_artifacts(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    assert package_all(build_options, result).variants

    dist = build_options.dist_dir
    for name in (
        "immich-cn-geodata-admin2-default-v1.zip",
        "immich-cn-geodata-admin2-full-v1.zip",
        "immich-cn-geodata-admin2-admin3-default-v1.zip",
        "immich-cn-geodata-admin2-admin3-full-v1.zip",
        "immich-cn-dataset-sqlite-v1.zip",
        "immich-cn-i18n-json-v1.zip",
        "immich-cn-manifest-json-v1.json",
        "immich-cn-patterns-tsv-v1.gz",
        "immich-cn-checksums-sha256-v1.txt",
    ):
        assert (dist / name).exists(), name

    manifest = json.loads((dist / "immich-cn-manifest-json-v1.json").read_text(encoding="utf-8"))
    assert manifest["tool"]["name"] == "immich-cn"
    assert isinstance(manifest["tool"]["revision"], str)
    assert manifest["artifactSpecVersion"] == 4
    assert len(manifest["artifacts"]) == 4
    assert len(manifest["assets"]) == 7
    assert "aliases" not in manifest and "legacyAliases" not in manifest and "variants" not in manifest
    first_artifact = manifest["artifacts"][0]
    assert first_artifact["id"].startswith("immich-cn.geodata.")
    assert "{" not in first_artifact["profile"] and "_" not in first_artifact["profile"]
    assert first_artifact["canonicalFile"].startswith("immich-cn-geodata-")
    assert manifest["dataset"]["file"] == "immich-cn-dataset-sqlite-v1.zip"
    assert manifest["dataset"]["format"] == "immich-cn.dataset/1"
    assert manifest["dataset"]["schemaVersion"] == 1
    assert manifest["license"]["code"] == "MIT"
    stats = manifest["stats"]
    assert stats["droppedPlaces"] > 0
    assert stats["perCountry"]["CN"] > 0
    assert sum(stats["perCountry"].values()) == stats["outputPlaces"]

    with zipfile.ZipFile(dist / "immich-cn-geodata-admin2-admin3-full-v1.zip") as zf:
        names = set(zf.namelist())
        assert "geodata/cities500.txt" in names
        assert "geodata/build-info.json" in names
        assert "geodata/NOTICE.txt" in names
        payload = zf.read("geodata/cities500.txt").decode("utf-8").splitlines()
    rows = {line.split("\t")[0]: line.split("\t") for line in payload}
    assert rows["9100"][1] == "苏州市 昆山市"
    assert "9101" in rows, "full 变体应保留人口为 0 的补充点位"

    with zipfile.ZipFile(dist / "immich-cn-geodata-admin2-default-v1.zip") as zf:
        payload = zf.read("geodata/cities500.txt").decode("utf-8").splitlines()
    rows = {line.split("\t")[0]: line.split("\t") for line in payload}
    assert rows["1886760"][1] == "苏州市"
    assert "9101" not in rows

    with zipfile.ZipFile(dist / "immich-cn-i18n-json-v1.zip") as zf:
        license_text = zf.read("LICENSE").decode("utf-8")
    assert "MIT License" in license_text
    assert "Copyright" in license_text

    checksums = (dist / "immich-cn-checksums-sha256-v1.txt").read_text(encoding="utf-8")
    assert "immich-cn-geodata-admin2-default-v1.zip" in checksums
    assert "immich-cn-dataset-sqlite-v1.zip" in checksums


def test_canonical_dataset_is_queryable_and_preserves_immich_boundary(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    package_all(build_options, result)

    archive_path = build_options.dist_dir / "immich-cn-dataset-sqlite-v1.zip"
    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == {
            "immich-cn-dataset-v1.sqlite",
            "schema.json",
            "NOTICE.txt",
            "README.txt",
        }
        schema = json.loads(archive.read("schema.json").decode("utf-8"))
        assert schema["compatibility"]["immich"].startswith("通过 geodata*.zip")
        database = build_options.work_dir / "extracted-dataset.sqlite"
        database.write_bytes(archive.read("immich-cn-dataset-v1.sqlite"))

    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            """
            SELECT country_name, admin1_name, admin2_name, admin3_name, in_default
            FROM localized_places
            WHERE geoname_id = 9100
            """
        ).fetchone()
        assert row == ("中国", "江苏省", "苏州市", "昆山市", 1)
        assert connection.execute("SELECT COUNT(*) FROM places").fetchone()[0] == result.stats.output_places
        assert connection.execute("SELECT COUNT(*) FROM place_names").fetchone()[0] == result.stats.output_places
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_canonical_dataset_is_deterministic(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    package_all(build_options, result)
    first = (build_options.dist_dir / "immich-cn-dataset-sqlite-v1.zip").read_bytes()
    package_all(build_options, result)
    second = (build_options.dist_dir / "immich-cn-dataset-sqlite-v1.zip").read_bytes()
    assert first == second


def test_checksums_ignore_unregistered_leftovers(build_options: BuildOptions) -> None:
    """dist 里的历史残留不能被写进校验和。

    发布路径是 `gh release upload ... dist/*`，残留文件会被一起上传；
    旧实现扫描整个 dist 目录，会替残留文件签名。
    """
    result = run_build(build_options)
    build_options.dist_dir.mkdir(parents=True, exist_ok=True)
    stray = build_options.dist_dir / "geodata_admin_2.zip"
    stray.write_bytes(b"legacy leftover")

    package_result = package_all(build_options, result)
    listing = package_result.checksums.read_text(encoding="utf-8")

    assert "geodata_admin_2.zip" not in listing
    assert "immich-cn-geodata-admin2-default-v1.zip" in listing
    assert "immich-cn-manifest-json-v1.json" in listing
    assert "immich-cn-checksums-sha256-v1.txt" not in listing  # 清单不登记自身


def test_package_removes_plain_patterns_table(build_options: BuildOptions) -> None:
    """明文变体表只是生成 gz 的中间产物，默认不保留（百 MiB 级磁盘浪费）。"""
    result = run_build(build_options)
    package_all(build_options, result)

    assert not (build_options.work_dir / "immich-cn-patterns-v1.tsv").exists()
    compressed = build_options.dist_dir / "immich-cn-patterns-tsv-v1.gz"
    assert compressed.exists()

    expected = build_options.work_dir / "expected-immich-cn-patterns-v1.tsv"
    write_patterns_table(expected, levels=load_levels(result.names_file), patterns=build_options.patterns)
    with gzip.open(compressed, "rb") as handle:
        assert handle.read() == expected.read_bytes()


def test_package_keeps_plain_patterns_table_with_keep_raw(tmp_path: Path) -> None:
    """--keep-raw 时应保留明文变体表，便于本地排查。"""
    keep = BuildOptions(
        work_dir=tmp_path / "build",
        dist_dir=tmp_path / "dist",
        cache_dir=tmp_path / "cache",
        config_dir=Path(__file__).resolve().parent.parent / "config",
        extra_countries=("CN",),
        patterns=("{admin_2}",),
        provider="offline",
        skip_fetch=True,
        keep_raw=True,
    )
    create_synthetic_sources(keep.work_dir, keep.work_dir / "i18n-iso-countries" / "langs")
    result = run_build(keep)
    package_all(keep, result)

    assert (keep.work_dir / "immich-cn-patterns-v1.tsv").exists()


def test_cleanup_removable_does_not_follow_sources_symlink(tmp_path: Path) -> None:
    work = tmp_path / "work"
    outside = tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    victim = outside / "alternateNamesV2.txt"
    victim.write_bytes(b"external")
    (work / "sources").symlink_to(outside, target_is_directory=True)

    result = SimpleNamespace(removable_paths=[work / "sources" / victim.name])
    freed = cleanup_removable(result, work_dir=work)  # type: ignore[arg-type]

    assert freed == 0
    assert victim.read_bytes() == b"external"


def test_cleanup_removable_deletes_only_inside_work_dir(tmp_path: Path) -> None:
    work = tmp_path / "work"
    sources = work / "sources"
    sources.mkdir(parents=True)
    removable = sources / "country.txt"
    removable.write_bytes(b"internal")

    result = SimpleNamespace(removable_paths=[removable])
    freed = cleanup_removable(result, work_dir=work)  # type: ignore[arg-type]

    assert freed == len(b"internal")
    assert not removable.exists()


def test_patterns_table_covers_all_levels(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    table = build_options.work_dir / "immich-cn-patterns-v1.tsv"
    rows = write_patterns_table(table, levels_file=result.names_file, patterns=build_options.patterns)
    assert rows == result.stats.output_places
    header, *body = table.read_text(encoding="utf-8").splitlines()
    assert header.startswith("geoname_id\t")
    assert len(body) == rows


def test_build_variants_covers_full_axis() -> None:
    variants = build_variants(("{admin_2}", "{admin_3}"))
    assert [(variant.profile, variant.full) for variant in variants] == [
        ("admin2", False),
        ("admin2", True),
        ("admin3", False),
        ("admin3", True),
    ]


def _make_tarball(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))


def test_extract_i18n_rejects_path_traversal(tmp_path: Path) -> None:
    """恶意 tarball 成员不得写到目标目录之外（tar-slip）。"""
    evil = tmp_path / "evil.tgz"
    _make_tarball(evil, {"package/langs/../../../ESCAPED.txt": b"pwned"})
    options = BuildOptions(work_dir=tmp_path / "build", dist_dir=tmp_path / "dist")

    with pytest.raises(ParseError):
        _extract_i18n(evil, options)
    assert not (tmp_path / "ESCAPED.txt").exists()


def test_extract_i18n_accepts_normal_tarball(tmp_path: Path) -> None:
    """正常 tarball 仍应被解出，避免因噎废食。"""
    good = tmp_path / "good.tgz"
    _make_tarball(
        good,
        {
            "package/langs/zh.json": b'{"locale":"zh"}',
            "package/LICENSE": b"MIT License\nCopyright (c) Test",
            "package/package.json": b"{}",
        },
    )
    options = BuildOptions(work_dir=tmp_path / "build", dist_dir=tmp_path / "dist")

    _extract_i18n(good, options)
    extracted = tmp_path / "build" / "i18n-iso-countries" / "langs" / "zh.json"
    assert extracted.read_text() == '{"locale":"zh"}'
    assert (tmp_path / "build" / "i18n-iso-countries" / "LICENSE").exists()


def test_min_population_threshold_boundary(tmp_path: Path) -> None:
    """非 full 变体的 100 人口阈值必须在边界处翻转（99 排除、100 保留）。"""
    cities = tmp_path / "cities500.txt"
    write_lines(cities, [])
    extra = tmp_path / "extra.txt"
    write_lines(
        extra,
        [
            geo_row(1, "P99", country="CN", admin1="04", population=99),
            geo_row(2, "P100", country="CN", admin1="04", population=100),
            geo_row(3, "P101", country="CN", admin1="04", population=101),
        ],
    )

    kept = {
        place.geoname_id
        for place in iter_output_places(cities500=cities, extra_file=extra, min_population=100, full=False)
    }
    assert kept == {2, 3}
    everything = {
        place.geoname_id
        for place in iter_output_places(cities500=cities, extra_file=extra, min_population=100, full=True)
    }
    assert everything == {1, 2, 3}
