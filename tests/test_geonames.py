from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from immich_cn.errors import ParseError
from immich_cn.geonames import (
    ADMIN_FEATURE_LEVELS,
    admin_code,
    build_admin_units,
    extract_archive_member,
    iter_alternate_names,
    iter_places,
    place_code,
    read_admin_codes,
    read_country_info,
)
from tests.synthetic import geo_row, write_lines


def test_read_admin_codes(synthetic_sources: Path) -> None:
    entries = read_admin_codes(synthetic_sources / "admin1CodesASCII.txt")
    assert entries["CN.22"].geoname_id == 1816670
    assert entries["CN.04"].name == "Jiangsu"


def test_read_admin_codes_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ParseError):
        read_admin_codes(tmp_path / "missing.txt")


def test_iter_places_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "places.txt"
    write_lines(path, [geo_row(1, "A"), "too\tfew", geo_row(2, "B")])
    places = list(iter_places(path))
    assert [place.geoname_id for place in places] == [1, 2]


def test_build_admin_units_extracts_adm3_and_adm4(synthetic_sources: Path) -> None:
    tables = build_admin_units([synthetic_sources / "CN.txt"])
    assert set(tables[3]) == {"CN.04.SZ.KS"}
    assert tables[4]["CN.04.SZ.KS.ZSZ"].name == "Zhoushi"
    assert ADMIN_FEATURE_LEVELS["ADM3"] == 3


def test_place_code_requires_full_chain(tmp_path: Path) -> None:
    path = tmp_path / "places.txt"
    write_lines(
        path,
        [
            geo_row(1, "A", feature_class="A", feature_code="ADM3", admin1="04", admin2="SZ", admin3="KS"),
            geo_row(2, "B", feature_class="A", feature_code="ADM3", admin1="04", admin2="SZ"),
        ],
    )
    places = list(iter_places(path))
    assert place_code(places[0], 3) == "CN.04.SZ.KS"
    assert place_code(places[1], 3) == ""


def test_admin_code_builds_incrementally() -> None:
    assert admin_code("CN", "04") == "CN.04"
    assert admin_code("CN", "04", "SZ") == "CN.04.SZ"
    assert admin_code("CN", "04", "SZ", "", "ZSZ") == "CN.04.SZ"


def test_read_country_info(synthetic_sources: Path) -> None:
    rows = read_country_info(synthetic_sources / "countryInfo.txt")
    assert [row.alpha2 for row in rows] == ["CN", "HK", "TW", "JP", "US"]
    assert rows[0].with_name("中国").name == "中国"


def test_iter_alternate_names_filters_by_wanted_ids(synthetic_sources: Path) -> None:
    records = list(iter_alternate_names(synthetic_sources / "alternateNamesV2.txt", {1886760}))
    assert {record.geoname_id for record in records} == {1886760}
    assert len(records) == 3


def test_extract_archive_member(tmp_path: Path) -> None:
    archive = tmp_path / "data.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested/hello.txt", "你好")
    target = extract_archive_member(archive, "hello.txt", tmp_path / "out" / "hello.txt")
    assert target.read_text(encoding="utf-8") == "你好"


def test_extract_archive_member_missing(tmp_path: Path) -> None:
    archive = tmp_path / "data.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("other.txt", "x")
    with pytest.raises(ParseError):
        extract_archive_member(archive, "hello.txt", tmp_path / "out.txt")
