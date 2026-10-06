"""行政层级表：把 GeoNames 的代码表转换为中文名称表。"""

from __future__ import annotations

from dataclasses import dataclass, field

from immich_cn.chinese import (
    SPECIAL_ADMIN_TOP_LEVEL,
    ChineseNameIndex,
    NameOverrides,
    pick_from_alternates,
    strip_suffix,
    to_variant,
)
from immich_cn.geonames import admin_code
from immich_cn.logging_setup import get_logger
from immich_cn.models import AdminEntry, Place, PlaceNames

logger = get_logger("hierarchy")

#: 这些国家/地区允许在缺少中文名时回退到"日文汉字"（官方写法本身是汉字）
KANJI_FALLBACK_COUNTRIES: frozenset[str] = frozenset({"JP"})


@dataclass(slots=True)
class Hierarchy:
    """代码 → 中文名 的四级行政表。"""

    admin1: dict[str, str] = field(default_factory=dict)
    admin2: dict[str, str] = field(default_factory=dict)
    admin3: dict[str, str] = field(default_factory=dict)
    admin4: dict[str, str] = field(default_factory=dict)

    def lookup(self, level: int, code: str) -> str:
        table = {1: self.admin1, 2: self.admin2, 3: self.admin3, 4: self.admin4}[level]
        return table.get(code, "")

    def as_stats(self) -> dict[str, int]:
        return {
            "admin1": len(self.admin1),
            "admin2": len(self.admin2),
            "admin3": len(self.admin3),
            "admin4": len(self.admin4),
        }


def translate_admin_codes(
    entries: dict[str, AdminEntry],
    index: ChineseNameIndex,
    *,
    fallback_to_ascii: bool = True,
) -> dict[str, str]:
    """把代码表翻译为中文；缺失时退回 GeoNames 名称并做繁简转换。"""
    translated: dict[str, str] = {}
    for code, entry in entries.items():
        name = index.get_admin(code) or index.get(entry.geoname_id)
        if not name and code.split(".")[0] in KANJI_FALLBACK_COUNTRIES:
            name = index.get_kanji(entry.geoname_id)
        if not name and fallback_to_ascii:
            name = to_variant(entry.name, index.variant)
        if name:
            translated[code] = name
    return translated


def translate_admin_units(
    units: dict[str, int],
    geoname_names: dict[str, tuple[int, str, tuple[str, ...]]],
    index: ChineseNameIndex,
) -> dict[str, str]:
    """翻译自建 admin3/admin4 表。

    ``units`` 为 ``code -> geonameId``，``geoname_names`` 为
    ``code -> (geonameId, name, alternateNames)``，便于在缺少中文别名时回退。
    """
    translated: dict[str, str] = {}
    for code, geoname_id in units.items():
        name = index.get(geoname_id) or index.get_admin(code)
        if not name and code.split(".")[0] in KANJI_FALLBACK_COUNTRIES:
            name = index.get_kanji(geoname_id)
        if not name:
            entry = geoname_names.get(code)
            if entry is not None:
                _, raw_name, alternates = entry
                name = pick_from_alternates(alternates, index.variant) or (
                    to_variant(raw_name, index.variant) if raw_name else ""
                )
        if name:
            translated[code] = name
    return translated


def resolve_place_names(
    place: Place,
    hierarchy: Hierarchy,
    index: ChineseNameIndex,
) -> PlaceNames:
    """根据行政代码表推导一个地点的四级中文名（不含后处理）。"""
    country_code = place.country_code
    a1, a2, a3, a4 = place.admin_chain()
    return PlaceNames(
        geoname_id=place.geoname_id,
        country=index.get_country(country_code) or country_code,
        admin_1=hierarchy.lookup(1, admin_code(country_code, a1)),
        admin_2=hierarchy.lookup(2, admin_code(country_code, a1, a2)),
        admin_3=hierarchy.lookup(3, admin_code(country_code, a1, a2, a3)),
        admin_4=hierarchy.lookup(4, admin_code(country_code, a1, a2, a3, a4)),
    )


def finalize_place_names(names: PlaceNames, country_code: str, overrides: NameOverrides) -> None:
    """在所有 provider 增强完成后整理层级并补齐缺口。"""
    for attribute in ("admin_1", "admin_2", "admin_3", "admin_4"):
        value = getattr(names, attribute)
        if value:
            setattr(names, attribute, strip_suffix(value, country_code, overrides))

    # 港澳在 GeoNames 中把"堂区/区"放在 admin1，这里重整为
    # admin_1=特别行政区、admin_2=区，并按需补充新界/九龙/香港岛前缀。
    top_level = SPECIAL_ADMIN_TOP_LEVEL.get(country_code)
    if top_level and names.admin_1 and names.admin_1 != top_level:
        district = names.admin_2 or names.admin_1
        names.admin_1 = top_level
        names.admin_2 = district
        if country_code == "HK" and not names.admin_3:
            region = overrides.hk_districts.get(district)
            names.admin_3 = f"{region} {district}" if region else district

    if top_level:
        names.admin_1 = strip_suffix(names.admin_1, country_code, overrides)

    names.fill_gaps()
