from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from immich_cn.build import _extract_i18n, load_levels, run_build, write_patterns_table
from immich_cn.config import BuildOptions
from immich_cn.errors import ParseError
from immich_cn.package import build_variants, package_all
from immich_cn.verify import assert_valid, verify_geodata


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

    # 非 full 变体：人口为 0 的补充点位不写入 geodata 目录
    assert "9101" not in rows
    assert "9100" in rows
    # 与 cities500 重复的记录（同 ID 或同坐标）必须只出现一次
    ids = [line.split("\t")[0] for line in cities]
    assert ids.count("1886760") == 1
    assert "9200" not in rows

    admin1 = (geodata / "admin1CodesASCII.txt").read_text(encoding="utf-8")
    assert "江苏省" in admin1
    country_info = (geodata / "countryInfo.txt").read_text(encoding="utf-8")
    assert "\t中国\t" in country_info

    levels = load_levels(result.names_file)
    # 元组顺序为 (country, admin_1, admin_2, admin_3, admin_4)
    assert levels[9100][2] == "苏州市"
    assert levels[9100][3] == "昆山市"
    assert levels[9100][4] == "周市镇"

    results = verify_geodata(geodata)
    assert_valid(results)


def test_build_is_idempotent(build_options: BuildOptions) -> None:
    first = run_build(build_options)
    second = run_build(build_options)
    assert first.stats.output_places == second.stats.output_places
    assert (second.geodata_dir / "cities500.txt").read_text(encoding="utf-8") == (
        first.geodata_dir / "cities500.txt"
    ).read_text(encoding="utf-8")


def test_package_produces_expected_artifacts(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    assert package_all(build_options, result).variants

    dist = build_options.dist_dir
    for name in (
        "geodata.zip",
        "geodata_full.zip",
        "geodata_admin_2.zip",
        "geodata_admin_2_full.zip",
        "geodata_admin_2_admin_3.zip",
        "geodata_admin_2_admin_3_full.zip",
        "i18n-iso-countries.zip",
        "manifest.json",
        "patterns.tsv.gz",
        "SHA256SUMS",
    ):
        assert (dist / name).exists(), name

    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tool"]["name"] == "immich-cn"
    assert len(manifest["variants"]) == 4
    assert manifest["license"]["code"] == "MIT"

    with zipfile.ZipFile(dist / "geodata_admin_2_admin_3_full.zip") as zf:
        names = set(zf.namelist())
        assert "geodata/cities500.txt" in names
        assert "geodata/build-info.json" in names
        payload = zf.read("geodata/cities500.txt").decode("utf-8").splitlines()
    rows = {line.split("\t")[0]: line.split("\t") for line in payload}
    assert rows["9100"][1] == "苏州市 昆山市"
    assert "9101" in rows, "full 变体应保留人口为 0 的补充点位"

    with zipfile.ZipFile(dist / "geodata_admin_2.zip") as zf:
        payload = zf.read("geodata/cities500.txt").decode("utf-8").splitlines()
    rows = {line.split("\t")[0]: line.split("\t") for line in payload}
    assert rows["1886760"][1] == "苏州市"
    assert "9101" not in rows

    checksums = (dist / "SHA256SUMS").read_text(encoding="utf-8")
    assert "geodata.zip" in checksums


def test_patterns_table_covers_all_levels(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    table = build_options.work_dir / "patterns.tsv"
    rows = write_patterns_table(table, levels_file=result.names_file, patterns=build_options.patterns)
    assert rows == result.stats.output_places
    header, *body = table.read_text(encoding="utf-8").splitlines()
    assert header.startswith("geoname_id\t")
    assert len(body) == rows


def test_build_variants_covers_full_axis() -> None:
    variants = build_variants(("{admin_2}", "{admin_3}"))
    assert [(variant.slug, variant.full) for variant in variants] == [
        ("admin_2", False),
        ("admin_2", True),
        ("admin_3", False),
        ("admin_3", True),
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
    _make_tarball(good, {"package/langs/zh.json": b'{"locale":"zh"}', "package/package.json": b"{}"})
    options = BuildOptions(work_dir=tmp_path / "build", dist_dir=tmp_path / "dist")

    _extract_i18n(good, options)
    extracted = tmp_path / "build" / "i18n-iso-countries" / "langs" / "zh.json"
    assert extracted.read_text() == '{"locale":"zh"}'
