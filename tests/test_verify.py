"""校验器的行为测试：确保检查项真的会失败，而不是"恒真"。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from immich_cn.build import run_build
from immich_cn.config import BuildOptions
from immich_cn.verify import verify_geodata


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


def test_broken_geojson_is_rejected(build_options: BuildOptions) -> None:
    result = run_build(build_options)
    (result.geodata_dir / "ne_10m_admin_0_countries.geojson").write_text("{not json", encoding="utf-8")
    assert "natural-earth" in _failures(result.geodata_dir)


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
