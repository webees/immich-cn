from __future__ import annotations

from pathlib import Path

from immich_cn.chinese import ChineseNameIndex, NameOverrides
from immich_cn.hierarchy import Hierarchy, finalize_place_names, resolve_place_names
from immich_cn.models import AdminEntry, Place
from tests.synthetic import geo_row


def make_place(**kwargs: object) -> Place:
    line = geo_row(1, "Sample", **kwargs)  # type: ignore[arg-type]
    place = Place.from_line(line)
    assert place is not None
    return place


def test_resolve_place_names_uses_hierarchy() -> None:
    hierarchy = Hierarchy(
        admin1={"CN.04": "江苏省"},
        admin2={"CN.04.SZ": "苏州市"},
        admin3={"CN.04.SZ.KS": "昆山市"},
        admin4={"CN.04.SZ.KS.ZSZ": "周市镇"},
    )
    index = ChineseNameIndex(names={})
    place = make_place(admin1="04", admin2="SZ", admin3="KS", admin4="ZSZ")
    names = resolve_place_names(place, hierarchy, index)
    assert names.admin_1 == "江苏省"
    assert names.admin_4 == "周市镇"


def test_finalize_fills_gaps() -> None:
    index = ChineseNameIndex()
    place = make_place(admin1="04", admin2="SZ")
    hierarchy = Hierarchy(admin1={"CN.04": "江苏省"}, admin2={"CN.04.SZ": "苏州市"})
    names = resolve_place_names(place, hierarchy, index)
    finalize_place_names(names, place.country_code, NameOverrides())
    assert names.admin_3 == "苏州市"
    assert names.admin_4 == "苏州市"


def test_finalize_rewrites_hong_kong_levels() -> None:
    overrides = NameOverrides(hk_districts={"元朗区": "新界"})
    place = make_place(country="HK", admin1="NYL")
    names = resolve_place_names(place, Hierarchy(admin1={"HK.NYL": "元朗区"}), ChineseNameIndex())
    finalize_place_names(names, "HK", overrides)
    assert names.admin_1 == "香港"
    assert names.admin_2 == "元朗区"
    assert names.admin_3 == "新界 元朗区"


def test_finalize_rewrites_macao_levels() -> None:
    overrides = NameOverrides()
    place = make_place(country="MO", admin1="11875154")
    names = resolve_place_names(place, Hierarchy(admin1={"MO.11875154": "花地玛堂区"}), ChineseNameIndex())
    finalize_place_names(names, "MO", overrides)
    assert names.admin_1 == "澳门"
    assert names.admin_2 == "花地玛堂区"


def test_strip_suffixes(tmp_path: Path) -> None:
    path = tmp_path / "overrides.toml"
    path.write_text('[rules.strip_suffixes]\nHK = ["特别行政区"]\n', encoding="utf-8")
    overrides = NameOverrides.load(path)
    assert overrides.strip_suffixes["HK"] == ("特别行政区",)


def test_overrides_load_rejects_bad_key(tmp_path: Path) -> None:
    path = tmp_path / "overrides.toml"
    path.write_text('[places]\n"abc" = "x"\n', encoding="utf-8")
    import pytest

    from immich_cn.errors import ConfigError

    with pytest.raises(ConfigError):
        NameOverrides.load(path)


def test_admin_entry_is_exported() -> None:
    assert AdminEntry(code="CN.04", name="Jiangsu").geoname_id is None
