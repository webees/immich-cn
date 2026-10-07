"""校验器的行为测试：确保检查项真的会失败，而不是"恒真"。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from immich_cn.pipeline import run_build
from immich_cn.settings import BuildOptions
from immich_cn.validation import (
    _check_admin,
    _check_cities500,
    _check_country_info,
    verify_geodata,
)
from tests.synthetic import geo_row, write_lines


def _failures(geodata: Path) -> dict[str, str]:
    return {result.name: result.detail for result in verify_geodata(geodata) if not result.passed}


def _rewrite(path: Path, transform: Callable[[list[str]], list[str]]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("".join(transform(lines)) + "\n", encoding="utf-8")


def test_baseline_dataset_passes(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    assert _failures(result.geodata_dir) == {}


def test_admin2_ascii_names_are_rejected(build_options: BuildOptions) -> None:
    """把中国 admin2 名称改回拼音后必须失败，证明该检查不是装饰性的。"""
    result = run_build(build_options)
    admin2 = result.geodata_dir / "admin2Codes.txt"

    def strip_chinese(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            fields = line.split("\t")
            if fields[0].startswith("CN."):
                fields[1] = fields[2] = "Pinyin Name"
            out.append("\t".join(fields) + "\n")
        return out

    _rewrite(admin2, strip_chinese)
    failures = _failures(result.geodata_dir)
    assert "admin2" in failures, failures


def test_japan_admin2_ascii_names_are_rejected(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    admin2 = result.geodata_dir / "admin2Codes.txt"

    def strip_japan(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            fields = line.split("\t")
            if fields[0].startswith("JP."):
                fields[1] = fields[2] = "Sapporo"
            out.append("\t".join(fields))
        return out

    admin2.write_text("\n".join(strip_japan(admin2.read_text(encoding="utf-8").splitlines())) + "\n", encoding="utf-8")
    failures = _failures(result.geodata_dir)
    assert "admin2" in failures, failures


def test_admin1_ascii_names_are_rejected(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    admin1 = result.geodata_dir / "admin1CodesASCII.txt"

    def strip_chinese(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            fields = line.split("\t")
            if fields[0].startswith("CN."):
                fields[1] = fields[2] = "Pinyin"
            out.append("\t".join(fields) + "\n")
        return out

    _rewrite(admin1, strip_chinese)
    failures = _failures(result.geodata_dir)
    assert "admin1" in failures, failures


def test_missing_admin2_codes_are_rejected(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    cities = result.geodata_dir / "cities500.txt"

    def drop_admin2(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            fields = line.split("\t")
            if len(fields) >= 19 and fields[8] == "CN":
                fields[11] = ""
            out.append("\t".join(fields) + "\n")
        return out

    _rewrite(cities, drop_admin2)
    failures = _failures(result.geodata_dir)
    assert "cities500-cn-admin2" in failures, failures


def test_unresolvable_admin2_codes_are_rejected(build_options: BuildOptions) -> None:
    """admin2 代码必须能在 admin2Codes.txt 中解析出名称，否则只能算"看起来有值"。"""
    result = run_build(build_options)
    admin2 = result.geodata_dir / "admin2Codes.txt"

    def drop_suzhou(lines: list[str]) -> list[str]:
        return [line for line in lines if not line.startswith("CN.04.SZ\t")]

    _rewrite(admin2, drop_suzhou)
    failures = _failures(result.geodata_dir)
    assert "cities500-cn-admin2-resolvable" in failures, failures


def test_missing_all_cn_cities_are_rejected(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    cities = result.geodata_dir / "cities500.txt"

    def drop_cn(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            fields = line.split("\t")
            if len(fields) >= 19 and fields[8] == "CN":
                continue
            out.append("\t".join(fields))
        return out

    cities.write_text("\n".join(drop_cn(cities.read_text(encoding="utf-8").splitlines())) + "\n", encoding="utf-8")
    assert "cities500-cn-cjk" in _failures(result.geodata_dir)


def test_missing_all_hk_cities_are_rejected(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    cities = result.geodata_dir / "cities500.txt"

    def drop_hk(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            fields = line.split("\t")
            if len(fields) >= 19 and fields[8] == "HK":
                continue
            out.append("\t".join(fields))
        return out

    cities.write_text("\n".join(drop_hk(cities.read_text(encoding="utf-8").splitlines())) + "\n", encoding="utf-8")
    assert "cities500-hk-cjk" in _failures(result.geodata_dir)


def test_hong_kong_ascii_names_are_rejected(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    cities = result.geodata_dir / "cities500.txt"

    def strip_hong_kong(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            fields = line.split("\t")
            if len(fields) >= 19 and fields[8] == "HK":
                fields[1] = fields[2] = "Tsuen Wan"
            out.append("\t".join(fields) + "\n")
        return out

    _rewrite(cities, strip_hong_kong)
    assert "cities500-hk-cjk" in _failures(result.geodata_dir)


def test_admin1_japan_region_thresholds(build_options: BuildOptions) -> None:
    """日本区域既必须参与校验，又必须允许约 10% 的官方假名地名。"""
    result = run_build(build_options)
    admin1 = result.geodata_dir / "admin1CodesASCII.txt"
    other_rows = [line for line in admin1.read_text(encoding="utf-8").splitlines() if not line.startswith("JP.")]

    def failures(chinese: int) -> dict[str, str]:
        rows = [f"JP.{i:02d}\t{'北海道' if i < chinese else 'Hokkaido'}\tHokkaido\t{2000 + i}" for i in range(10)]
        write_lines(admin1, [*other_rows, *rows])
        return _failures(result.geodata_dir)

    assert "admin1" in failures(5), "日本区域未被单独校验"
    assert "admin1" in failures(8), "日本区域阈值过松"
    assert "admin1" not in failures(9), "日本区域阈值不应拒绝官方假名比例"


def test_broken_geojson_is_rejected(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    (result.geodata_dir / "ne_10m_admin_0_countries.geojson").write_text("{not json", encoding="utf-8")
    assert "natural-earth" in _failures(result.geodata_dir)


def test_geojson_missing_immich_properties_is_rejected(build_options: BuildOptions) -> None:
    """Immich 把 properties.TYPE 等写入 NOT NULL 列，缺字段会让 country fallback 失败。"""
    result = run_build(build_options)
    path = result.geodata_dir / "ne_10m_admin_0_countries.geojson"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["features"][0]["properties"].pop("TYPE")
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert "natural-earth" in _failures(result.geodata_dir)


def test_geojson_non_polygon_geometry_is_rejected(build_options: BuildOptions) -> None:
    """Immich 把 geometry.coordinates 拼成 PostgreSQL polygon，点几何无法入库。"""
    result = run_build(build_options)
    path = result.geodata_dir / "ne_10m_admin_0_countries.geojson"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["features"][0]["geometry"] = {"type": "Point", "coordinates": [104.0, 35.0]}
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert "natural-earth" in _failures(result.geodata_dir)


def test_overlong_place_name_is_rejected(build_options: BuildOptions) -> None:
    """Immich geodata_places.name 是 varchar(200)，超长会让整个 import 失败。"""
    result = run_build(build_options)
    cities = result.geodata_dir / "cities500.txt"
    lines = cities.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        fields = line.split("\t")
        if fields[8] == "US":
            fields[1] = "x" * 201
            lines[index] = "\t".join(fields)
            break
    else:
        raise AssertionError("测试前提：样例数据应包含 US 记录")
    cities.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    assert "cities500-immich-columns" in _failures(result.geodata_dir)


def test_invalid_modification_date_is_rejected(build_options: BuildOptions) -> None:
    """Immich geodata_places.modificationDate 是 NOT NULL date 列，空值无法导入。"""
    result = run_build(build_options)
    cities = result.geodata_dir / "cities500.txt"
    lines = cities.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        fields = line.split("\t")
        if fields[8] == "US":
            fields[18] = ""
            lines[index] = "\t".join(fields)
            break
    else:
        raise AssertionError("测试前提：样例数据应包含 US 记录")
    cities.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    assert "cities500-modification-date" in _failures(result.geodata_dir)


def test_duplicate_geoname_ids_are_rejected(build_options: BuildOptions) -> None:
    """cities500 出现重复 GeoNames ID 时必须失败（重复点位会让 Import 覆盖数据）。"""
    result = run_build(build_options)
    cities = result.geodata_dir / "cities500.txt"
    lines = cities.read_text(encoding="utf-8").splitlines()
    duplicated = [line for line in lines if line.startswith("1886760\t")]
    assert duplicated, "测试前提：样例数据应包含 1886760"
    cities.write_text("".join(line + "\n" for line in [*lines, duplicated[0]]), encoding="utf-8")

    assert "cities500-duplicates" in _failures(result.geodata_dir)


def test_missing_file_is_rejected(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    (result.geodata_dir / "countryInfo.txt").unlink()
    results = verify_geodata(result.geodata_dir)
    assert results[0].name == "required-files"
    assert results[0].passed is False


def test_traditional_variant_translates_country_names(build_options: BuildOptions) -> None:
    traditional = BuildOptions(
        work_dir=build_options.work_dir,
        dist_dir=build_options.dist_dir,
        cache_dir=build_options.cache_dir,
        config_dir=build_options.config_dir,
        extra_countries=build_options.extra_countries,
        patterns=build_options.patterns,
        provider="offline",
        chinese_variant="hant",
        skip_fetch=True,
    )
    result = run_build(traditional)

    country_info = (result.geodata_dir / "countryInfo.txt").read_text(encoding="utf-8")
    us_row = next(line for line in country_info.splitlines() if line.startswith("US\t"))
    assert us_row.split("\t")[4] == "美國", us_row

    legacy = (result.langs_dir / "en.json").read_text(encoding="utf-8")
    assert "美國" in legacy


def test_traditional_variant_converts_hong_kong_and_macao_names(build_options: BuildOptions) -> None:
    traditional = BuildOptions(
        work_dir=build_options.work_dir,
        dist_dir=build_options.dist_dir,
        cache_dir=build_options.cache_dir,
        config_dir=build_options.config_dir,
        extra_countries=build_options.extra_countries,
        patterns=build_options.patterns,
        provider="offline",
        chinese_variant="hant",
        skip_fetch=True,
    )
    result = run_build(traditional)

    admin1 = (result.geodata_dir / "admin1CodesASCII.txt").read_text(encoding="utf-8")
    assert "HK.NYL\t香港特別行政區\t香港特別行政區\t" in admin1
    assert "MO.11875154\t澳門特別行政區\t澳門特別行政區\t" in admin1

    cities = (result.geodata_dir / "cities500.txt").read_text(encoding="utf-8").splitlines()
    hk = next(line.split("\t") for line in cities if line.startswith("1819729\t"))
    assert hk[1] == "元朗區", hk


# --------------------------------------------------------------------------
# 阈值边界（M2 阈值反演）：刚好等于阈值必须通过，低一点必须失败
# --------------------------------------------------------------------------


def test_country_info_threshold_boundary(tmp_path: Path) -> None:
    def build(chinese: int) -> Path:
        path = tmp_path / f"countryInfo-{chinese}.txt"
        write_lines(
            path,
            [
                f"C{i:02d}\tXXX\t000\tXX\t{'中国' if i < chinese else 'Country'}\t\t\t\t\t\t\t\t\t\t\t\t\t\t"
                for i in range(10)
            ],
        )
        return path

    at_threshold = _check_country_info(build(10))  # 10/10 = 1.00
    assert at_threshold.passed is True, at_threshold.detail
    below = _check_country_info(build(9))  # 9/10 = 0.90
    assert below.passed is False, below.detail


def test_country_info_rejects_two_missing_names(tmp_path: Path) -> None:
    path = tmp_path / "countryInfo-98.txt"
    write_lines(
        path,
        [f"C{i:03d}\tXXX\t000\tXX\t{'中国' if i < 98 else 'Country'}\t\t\t\t\t\t\t\t\t\t\t\t\t\t" for i in range(100)],
    )
    result = _check_country_info(path)
    assert result.passed is False, result.detail


def test_country_info_rejects_malformed_rows(tmp_path: Path) -> None:
    path = tmp_path / "countryInfo-malformed.txt"
    write_lines(
        path,
        [
            "CN\tCHN\t156\tCH\t中国\tBeijing\t9596961\t1330044000\tAS\t.cn\tCNY\tYuan\t86\t######\t\tzh\t1814991\t",
            "XX\tXXX\t999\tXX",
        ],
    )
    result = _check_country_info(path)
    assert result.passed is False, result.detail


def test_admin_country_ratio_threshold_boundary(tmp_path: Path) -> None:
    def build(chinese: int) -> Path:
        path = tmp_path / f"admin1-{chinese}.txt"
        write_lines(
            path,
            [f"CN.{i:02d}\t{'浙江省' if i < chinese else 'Pinyin'}\tSame\t{1000 + i}" for i in range(20)],
        )
        return path

    at_threshold = _check_admin(build(19), "admin1", min_overall_ratio=0.5, min_country_ratio=0.95)
    assert at_threshold.passed is True, at_threshold.detail
    below = _check_admin(build(18), "admin1", min_overall_ratio=0.5, min_country_ratio=0.95)
    assert below.passed is False, below.detail


def test_admin_region_english_entry_is_rejected(tmp_path: Path) -> None:
    """港澳条目里出现英文名（例如 GeoNames 缺中文别名）必须被判失败。"""
    path = tmp_path / "admin1.txt"
    rows = [f"HK.K{i:02d}\t元朗区\tYuen Long\t{1000 + i}" for i in range(17)]
    rows.append("HK.K17\tSouthern District\tSouthern District\t2000")  # 英文条目
    rows.extend(f"CN.{i:02d}\t浙江省\tZhejiang\t{3000 + i}" for i in range(19))
    rows.append("TW.01\t台湾省\tTaiwan\t4000")
    rows.append("MO.1\t澳门特别行政区\tMacau\t5000")
    write_lines(path, rows)

    result = _check_admin(
        path,
        "admin1",
        min_overall_ratio=0.5,
        min_country_ratio=0.95,
        regions=("CN.", "HK.", "MO.", "TW."),
    )
    assert result.passed is False
    assert "HK.*" in result.detail


def test_admin_overall_ratio_threshold_boundary(tmp_path: Path) -> None:
    """admin1 的"整体中文覆盖率"阈值（0.5）也必须在边界处翻转。"""
    chinese_rows = [f"CN.{i:02d}\t浙江省\tZhejiang\t{1000 + i}" for i in range(10)]
    ascii_rows = [f"US.S{i:02d}\tState{i}\tState{i}\t{2000 + i}" for i in range(10)]
    path = tmp_path / "admin1-overall.txt"
    write_lines(path, chinese_rows + ascii_rows)  # 10/20 = 0.50

    at_threshold = _check_admin(path, "admin1", min_overall_ratio=0.5, min_country_ratio=0.95)
    assert at_threshold.passed is True, at_threshold.detail

    write_lines(path, chinese_rows + ascii_rows + ["US.S10\tState10\tState10\t2010"])  # 10/21
    below = _check_admin(path, "admin1", min_overall_ratio=0.5, min_country_ratio=0.95)
    assert below.passed is False, below.detail


def test_admin_region_ratio_threshold_boundary(tmp_path: Path) -> None:
    """港澳台按地区的中文覆盖率阈值（0.95）必须在边界处翻转。"""
    others = ["CN.01\t浙江省\tZhejiang\t1", "TW.01\t台湾省\tTaiwan\t2", "MO.1\t澳门特别行政区\tMacau\t3"]
    path = tmp_path / "admin1-region.txt"

    at_threshold = [f"HK.K{i:02d}\t元朗区\tYuen Long\t{100 + i}" for i in range(19)]
    at_threshold.append("HK.K19\tSouthern District\tSouthern District\t119")  # 19/20 = 0.95
    write_lines(path, at_threshold + others)
    result = _check_admin(
        path, "admin1", min_overall_ratio=0.5, min_country_ratio=0.95, regions=("CN.", "HK.", "MO.", "TW.")
    )
    assert result.passed is True, result.detail

    below_threshold = [
        *at_threshold[:18],
        "HK.K18\tSouthern District\tSouthern District\t118",  # 18/20 = 0.90
        "HK.K19\tSouthern District\tSouthern District\t119",
    ]
    write_lines(path, below_threshold + others)
    result = _check_admin(
        path, "admin1", min_overall_ratio=0.5, min_country_ratio=0.95, regions=("CN.", "HK.", "MO.", "TW.")
    )
    assert result.passed is False, result.detail


def test_admin_japan_region_ratio_threshold_boundary(tmp_path: Path) -> None:
    """日本允许少量假名名，但自定义阈值仍必须在 90% 边界处翻转。"""
    others = ["CN.01\t浙江省\tZhejiang\t1", "CN.02\t江苏省\tJiangsu\t2", "HK.K01\t中西区\tCentral\t3"]
    path = tmp_path / "admin1-japan.txt"

    at_threshold = [f"JP.{i:02d}\t東京都\tTokyo\t{100 + i}" for i in range(9)]
    at_threshold.append("JP.09\tTokyo\tTokyo\t109")  # 9/10 = 0.90
    write_lines(path, at_threshold + others)
    result = _check_admin(
        path,
        "admin1",
        min_overall_ratio=0.5,
        min_country_ratio=0.95,
        regions=("JP.",),
        region_min_ratios={"JP.": 0.90},
    )
    assert result.passed is True, result.detail

    below_threshold = [*at_threshold[:8], "JP.08\tTokyo\tTokyo\t108", "JP.09\tTokyo\tTokyo\t109"]
    write_lines(path, below_threshold + others)
    result = _check_admin(
        path,
        "admin1",
        min_overall_ratio=0.5,
        min_country_ratio=0.95,
        regions=("JP.",),
        region_min_ratios={"JP.": 0.90},
    )
    assert result.passed is False, result.detail


def _cities(rows: int, chinese: int, with_admin2: int) -> list[str]:
    out = []
    for i in range(rows):
        out.append(
            geo_row(
                1_000_000 + i,
                "苏州市" if i < chinese else "Suzhou",
                country="CN",
                admin1="04",
                admin2=f"A{i:03d}" if i < with_admin2 else "",
                latitude=str(30 + i / 1000),
                longitude=str(120 + i / 1000),
            )
        )
    return out


def test_cities500_requires_19_fields(tmp_path: Path) -> None:
    valid = _cities(1, 1, 1)[0].split("\t")
    assert len(valid) == 19

    def check(width: int) -> bool:
        path = tmp_path / f"cities-width-{width}.txt"
        write_lines(path, ["\t".join(valid[:width])])
        results = _check_cities500(
            path,
            min_cn_cjk_ratio=0.9,
            min_cn_admin2_code_ratio=0.9,
            admin2_codes={"CN.04.A000"},
        )
        return {result.name: result for result in results}["cities500"].passed

    assert check(19) is True
    assert check(18) is False


def test_cities500_rejects_non_integer_geoname_id(tmp_path: Path) -> None:
    fields = _cities(1, 1, 1)[0].split("\t")
    fields[0] = "not-an-id"
    path = tmp_path / "cities-invalid-id.txt"
    write_lines(path, ["\t".join(fields)])

    results = _check_cities500(
        path,
        min_cn_cjk_ratio=0.9,
        min_cn_admin2_code_ratio=0.9,
        admin2_codes={"CN.04.A000"},
    )
    result = {item.name: item for item in results}["cities500"]
    assert result.passed is False, result.detail


def test_cities500_coordinate_boundaries(tmp_path: Path) -> None:
    valid = _cities(1, 1, 1)[0].split("\t")

    def check(latitude: str, longitude: str) -> bool:
        fields = list(valid)
        fields[4] = latitude
        fields[5] = longitude
        path = tmp_path / f"cities-{latitude}-{longitude}.txt"
        write_lines(path, ["\t".join(fields)])
        results = _check_cities500(
            path,
            min_cn_cjk_ratio=0.9,
            min_cn_admin2_code_ratio=0.9,
            admin2_codes={"CN.04.A000"},
        )
        return {item.name: item for item in results}["cities500"].passed

    assert check("90", "180") is True
    assert check("-90", "-180") is True
    assert check("90.0001", "0") is False
    assert check("0", "180.0001") is False
    assert check("nan", "0") is False
    assert check("inf", "0") is False


def test_cities500_cjk_ratio_threshold_boundary(tmp_path: Path) -> None:
    def check(chinese: int):
        path = tmp_path / f"cities-cjk-{chinese}.txt"
        write_lines(path, _cities(10, chinese, 10))
        results = _check_cities500(
            path,
            min_cn_cjk_ratio=0.9,
            min_cn_admin2_code_ratio=0.9,
            admin2_codes={f"CN.04.A{i:03d}" for i in range(10)},
        )
        return {result.name: result for result in results}["cities500-cn-cjk"]

    assert check(9).passed is True, check(9).detail  # 9/10 = 0.90
    assert check(8).passed is False, check(8).detail


def test_hk_cjk_threshold_passes_but_strict_fails(tmp_path: Path) -> None:
    """HK 阈值是 99%：100 条里缺 1 条仍通过阈值检查，严格检查必须失败。"""
    rows = [
        geo_row(
            2_000_000 + i,
            "沙田区" if i else "Sha Tin",
            country="HK",
            admin1="NST",
            latitude=str(22 + i / 1000),
            longitude=str(114 + i / 1000),
        )
        for i in range(100)
    ]
    path = tmp_path / "cities-hk.txt"
    write_lines(path, rows)
    results = {
        result.name: result
        for result in _check_cities500(
            path,
            min_cn_cjk_ratio=0.0,
            min_hk_cjk_ratio=0.99,
            min_cn_admin2_code_ratio=0.0,
        )
    }

    assert results["cities500-hk-cjk"].passed is True  # 99/100 = 99%，达到阈值
    assert results["chinese-regions-cjk-strict"].passed is False  # 但严格检查必须失败


def test_cities500_cjk_strict_requires_zero_missing(tmp_path: Path) -> None:
    """阈值检查允许少量缺失，严格检查必须零容忍（与打包期护栏一致）。"""

    def check(chinese: int) -> dict[str, bool]:
        path = tmp_path / f"cities-strict-{chinese}.txt"
        write_lines(path, _cities(10, chinese, 10))
        results = _check_cities500(
            path,
            min_cn_cjk_ratio=0.9,
            min_cn_admin2_code_ratio=0.9,
            admin2_codes={f"CN.04.A{i:03d}" for i in range(10)},
        )
        return {result.name: result.passed for result in results}

    partial = check(9)
    assert partial["cities500-cn-cjk"] is True  # 9/10 达到 90% 阈值
    assert partial["chinese-regions-cjk-strict"] is False  # 但严格检查必须失败

    full = check(10)
    assert full["chinese-regions-cjk-strict"] is True


def test_cities500_admin2_code_ratio_threshold_boundary(tmp_path: Path) -> None:
    def check(with_admin2: int):
        path = tmp_path / f"cities-a2-{with_admin2}.txt"
        write_lines(path, _cities(10, 10, with_admin2))
        results = _check_cities500(
            path,
            min_cn_cjk_ratio=0.9,
            min_cn_admin2_code_ratio=0.9,
            admin2_codes={f"CN.04.A{i:03d}" for i in range(10)},
        )
        return {result.name: result for result in results}["cities500-cn-admin2"]

    assert check(9).passed is True, check(9).detail  # 9/10 = 0.90
    assert check(8).passed is False, check(8).detail


def test_cities500_admin2_resolvable_threshold_boundary(tmp_path: Path) -> None:
    def check(resolvable: int):
        path = tmp_path / f"cities-res-{resolvable}.txt"
        write_lines(path, _cities(100, 100, 100))
        codes = {f"CN.04.A{i:03d}" for i in range(resolvable)}
        results = _check_cities500(
            path,
            min_cn_cjk_ratio=0.9,
            min_cn_admin2_code_ratio=0.9,
            min_cn_admin2_resolved_ratio=0.99,
            admin2_codes=codes,
        )
        return {result.name: result for result in results}["cities500-cn-admin2-resolvable"]

    assert check(99).passed is True, check(99).detail  # 99/100 = 0.99
    assert check(98).passed is False, check(98).detail


def test_cities500_hong_kong_cjk_ratio_threshold_boundary(tmp_path: Path) -> None:
    def check(chinese: int):
        path = tmp_path / f"cities-hk-{chinese}.txt"
        rows = [
            geo_row(
                2_000_000 + i,
                "荃湾区" if i < chinese else "Tsuen Wan",
                country="HK",
                admin1="NTW",
                latitude=str(22 + i / 1000),
                longitude=str(114 + i / 1000),
            )
            for i in range(100)
        ]
        write_lines(path, rows)
        results = _check_cities500(
            path,
            min_cn_cjk_ratio=0.9,
            min_hk_cjk_ratio=0.99,
            min_cn_admin2_code_ratio=0.9,
        )
        return {result.name: result for result in results}["cities500-hk-cjk"]

    assert check(99).passed is True, check(99).detail  # 99/100 = 0.99
    assert check(98).passed is False, check(98).detail


def test_missing_country_records_fail_even_with_zero_ratio_threshold(tmp_path: Path) -> None:
    path = tmp_path / "cities-only-us.txt"
    write_lines(
        path,
        [
            geo_row(
                3_000_000,
                "New York",
                country="US",
                admin1="NY",
                latitude="40.7",
                longitude="-74.0",
            )
        ],
    )
    results = {
        result.name: result
        for result in _check_cities500(
            path,
            min_cn_cjk_ratio=0.0,
            min_hk_cjk_ratio=0.0,
            min_cn_admin2_code_ratio=0.0,
        )
    }
    assert results["cities500-cn-cjk"].passed is False
    assert results["cities500-hk-cjk"].passed is False
