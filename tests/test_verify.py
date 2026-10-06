"""校验器的行为测试：确保检查项真的会失败，而不是"恒真"。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from immich_cn.build import run_build
from immich_cn.config import BuildOptions
from immich_cn.verify import (
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


def test_broken_geojson_is_rejected(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    (result.geodata_dir / "ne_10m_admin_0_countries.geojson").write_text("{not json", encoding="utf-8")
    assert "natural-earth" in _failures(result.geodata_dir)


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

    at_threshold = _check_country_info(build(9))  # 9/10 = 0.90
    assert at_threshold.passed is True, at_threshold.detail
    below = _check_country_info(build(8))  # 8/10 = 0.80
    assert below.passed is False, below.detail


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
