"""中文名称解析：语言优先级、繁简转换与人工覆盖。"""

from __future__ import annotations

import tomllib
import warnings
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import zhconv

from immich_cn.config import ChineseVariant
from immich_cn.errors import ConfigError
from immich_cn.logging_setup import get_logger

logger = get_logger("chinese")

#: 港澳在 GeoNames 中使用堂区/区作为一级行政区，这里统一为特别行政区名称。
SPECIAL_ADMIN_TOP_LEVEL: dict[str, str] = {
    "HK": "香港特别行政区",
    "MO": "澳门特别行政区",
}

#: 内置的行政区后缀裁剪规则，避免缺少 config 目录时输出冗长后缀。
DEFAULT_STRIP_SUFFIXES: dict[str, tuple[str, ...]] = {
    "CN": ("特别行政区",),
    "HK": ("特别行政区",),
    "MO": ("特别行政区",),
}

#: 香港 18 区的区域归类（中西区/湾仔/东区/南区属香港岛，其余为九龙或新界）。
DEFAULT_HK_DISTRICTS: dict[str, str] = {
    "中西区": "香港岛",
    "中环": "香港岛",
    "湾仔区": "香港岛",
    "湾仔": "香港岛",
    "东区": "香港岛",
    "南区": "香港岛",
    "油尖旺区": "九龙",
    "油尖旺": "九龙",
    "深水埗区": "九龙",
    "深水埗": "九龙",
    "九龙城区": "九龙",
    "九龙城": "九龙",
    "黄大仙区": "九龙",
    "黄大仙": "九龙",
    "观塘区": "九龙",
    "观塘": "九龙",
    "葵青区": "新界",
    "葵青": "新界",
    "荃湾区": "新界",
    "荃湾": "新界",
    "屯门区": "新界",
    "屯门": "新界",
    "元朗区": "新界",
    "元朗": "新界",
    "北区": "新界",
    "大埔区": "新界",
    "大埔": "新界",
    "沙田区": "新界",
    "沙田": "新界",
    "西贡区": "新界",
    "西贡": "新界",
    "离岛区": "新界",
    "离岛": "新界",
}

#: 中文子标签优先级，索引越小越优先。项目默认输出简体，因此 zh-Hans 系最优先。
LANGUAGE_PRIORITY: tuple[str, ...] = (
    "zh-hans",
    "zh-cn",
    "zh-sg",
    "zh-my",
    "zh",
    "zh-hant",
    "zh-tw",
    "zh-hk",
    "zh-mo",
)

_VARIANT_TARGET: dict[ChineseVariant, str] = {"hans": "zh-cn", "hant": "zh-hant"}


def _preload_dictionary() -> None:
    """预加载 zhconv 字典。

    zhconv 首次加载时会以未关闭的文件句柄读取字典并抛出 ``ResourceWarning``，
    在 ``-W error`` 环境下会变成异常，因此在导入阶段一次性静默预热。
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        zhconv.convert("预加载", "zh-cn")


_preload_dictionary()


def to_variant(text: str, variant: ChineseVariant = "hans") -> str:
    """按目标字形转换中文文本。"""
    if not text:
        return text
    return cast(str, zhconv.convert(text, _VARIANT_TARGET[variant]))


def has_cjk(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff" for char in text)


def is_chinese_only(text: str) -> bool:
    """全部为 CJK 字符（含中日韩共用区）时返回 True。"""
    return bool(text) and all(
        "\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff" or char in "·・" for char in text
    )


def language_rank(language: str) -> int | None:
    """返回中文语言标签的优先级；非中文返回 None。"""
    normalized = language.strip().lower().replace("_", "-")
    if not normalized.startswith("zh"):
        return None
    if normalized in LANGUAGE_PRIORITY:
        return LANGUAGE_PRIORITY.index(normalized)
    # 处理 zh-Hans-CN / zh-Hant-TW 这类带地区的组合标签。
    for index, candidate in enumerate(LANGUAGE_PRIORITY):
        if normalized.startswith(f"{candidate}-"):
            return index
    return len(LANGUAGE_PRIORITY)


def is_japanese_language(language: str) -> bool:
    """是否为日语标签；必须排除 `jam` 等仅前缀相同的语言码。"""
    normalized = language.strip().lower().replace("_", "-")
    return normalized == "ja" or normalized.startswith("ja-")


def pick_from_alternates(candidates: Iterable[str], variant: ChineseVariant = "hans") -> str | None:
    """从 places 记录的 alternatenames 列中挑一个最合适的中文名。"""
    best: tuple[int, int, str] | None = None
    for index, candidate in enumerate(candidates):
        value = candidate.strip()
        if not value or not has_cjk(value):
            continue
        converted = to_variant(value, variant)
        score = (0 if is_chinese_only(converted) else 1, index, converted)
        if best is None or score < best:
            best = score
    return best[2] if best else None


@dataclass(slots=True)
class NameOverrides:
    """人工纠错表，位于 ``config/overrides.toml``。"""

    places: dict[int, str] = field(default_factory=dict)
    admins: dict[str, str] = field(default_factory=dict)
    countries: dict[str, str] = field(default_factory=dict)
    hk_districts: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HK_DISTRICTS))
    strip_suffixes: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_STRIP_SUFFIXES))

    @classmethod
    def load(cls, path: Path | None) -> NameOverrides:
        if path is None or not path.exists():
            return cls()
        try:
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ConfigError(f"无法解析覆盖表 {path}：{error}") from error

        places_raw = payload.get("places", {})
        admins_raw = payload.get("admins", {})
        countries_raw = payload.get("countries", {})
        rules_raw = payload.get("rules", {})
        if not isinstance(places_raw, dict) or not isinstance(admins_raw, dict):
            raise ConfigError("overrides.toml 的 [places] / [admins] 必须是表")

        places: dict[int, str] = {}
        for key, value in places_raw.items():
            if not str(key).strip().isdigit():
                raise ConfigError(f"[places] 的键必须是 GeoNames ID：{key!r}")
            if not isinstance(value, str):
                raise ConfigError(f"[places].{key} 必须是字符串")
            places[int(key)] = value

        strip_suffixes: dict[str, tuple[str, ...]] = dict(DEFAULT_STRIP_SUFFIXES)
        if isinstance(rules_raw, dict):
            raw_suffixes = rules_raw.get("strip_suffixes", {})
            if isinstance(raw_suffixes, dict):
                for country, values in raw_suffixes.items():
                    if isinstance(values, list) and all(isinstance(item, str) for item in values):
                        strip_suffixes[str(country)] = tuple(values)

        hk_districts = dict(DEFAULT_HK_DISTRICTS)
        if isinstance(rules_raw, dict):
            raw_districts = rules_raw.get("hk_districts", {})
            if isinstance(raw_districts, dict):
                hk_districts.update({str(key): str(value) for key, value in raw_districts.items()})

        return cls(
            places=places,
            admins={str(k): str(v) for k, v in admins_raw.items()},
            countries={str(k): str(v) for k, v in countries_raw.items()},
            hk_districts=hk_districts,
            strip_suffixes=strip_suffixes,
        )


@dataclass(slots=True)
class ChineseNameIndex:
    """geonameId → 中文名 的索引。"""

    names: dict[int, str] = field(default_factory=dict)
    #: 非中文但可直接显示的名称（目前只用于日本的日文汉字），按国家受限使用
    kanji_names: dict[int, str] = field(default_factory=dict)
    overrides: NameOverrides = field(default_factory=NameOverrides)
    variant: ChineseVariant = "hans"
    _ranks: dict[int, tuple[int, int]] = field(default_factory=dict, init=False, repr=False)
    _kanji_ranks: dict[int, int] = field(default_factory=dict, init=False, repr=False)

    def add_candidate(self, geoname_id: int, language: str, name: str, *, preferred: bool, historic: bool) -> None:
        if historic:
            return
        rank = language_rank(language)
        if rank is None:
            return
        value = name.strip()
        if not value:
            return
        current = self._ranks.get(geoname_id)
        # 越小的 (rank, 0/1) 越优先：先看语言，再看 isPreferredName。
        score = (rank, 0 if preferred else 1)
        if current is None or score < current:
            self.names[geoname_id] = value
            self._ranks[geoname_id] = score

    def add_kanji_candidate(self, geoname_id: int, language: str, name: str, *, preferred: bool) -> None:
        """记录日文汉字名称。

        日本地名的官方写法就是汉字（如 座間市），比 GeoNames 的罗马字更接近中文用户预期；
        但这不是中文，必须由国家层面显式启用（见 ``KANJI_FALLBACK_COUNTRIES``）。
        """
        if not is_japanese_language(language):
            return
        value = name.strip()
        if not value or not has_cjk(value):
            return
        score = 0 if preferred else 1
        current = self._kanji_ranks.get(geoname_id)
        if current is None or score < current:
            self.kanji_names[geoname_id] = value
            self._kanji_ranks[geoname_id] = score

    def get(self, geoname_id: int | None) -> str | None:
        """返回转换到目标字形并应用覆盖后的名称。"""
        if geoname_id is None:
            return None
        override = self.overrides.places.get(geoname_id)
        if override is not None:
            return to_variant(override, self.variant)
        raw = self.names.get(geoname_id)
        if raw is None:
            return None
        return to_variant(raw, self.variant)

    def get_admin(self, code: str) -> str | None:
        override = self.overrides.admins.get(code)
        if override is None:
            return None
        return to_variant(override, self.variant)

    def get_kanji(self, geoname_id: int | None) -> str | None:
        """返回日文汉字名称（转换为目标字形），没有则返回 None。"""
        if geoname_id is None:
            return None
        raw = self.kanji_names.get(geoname_id)
        if raw is None:
            return None
        return to_variant(raw, self.variant)

    def get_country(self, alpha2: str) -> str | None:
        override = self.overrides.countries.get(alpha2.upper())
        if override is None:
            return None
        return to_variant(override, self.variant)

    def stats(self) -> dict[str, int]:
        return {"names": len(self.names), "overrides": len(self.overrides.places)}


def build_name_index(
    alternate_names: Iterator[tuple[int, str, str, bool, bool]],
    *,
    overrides: NameOverrides,
    variant: ChineseVariant = "hans",
) -> ChineseNameIndex:
    """消费 alternateNames 记录并构造中文名索引。"""
    index = ChineseNameIndex(overrides=overrides, variant=variant)
    count = 0
    for geoname_id, language, name, preferred, historic in alternate_names:
        count += 1
        index.add_candidate(geoname_id, language, name, preferred=preferred, historic=historic)
        if not historic:
            index.add_kanji_candidate(geoname_id, language, name, preferred=preferred)
        if count % 1_000_000 == 0:
            logger.debug("已处理 %d 条候选名称", count)
    logger.info("中文名索引完成：%d 条候选，命中 %d 个 GeoNames ID", count, len(index.names))
    return index


def strip_suffix(
    value: str,
    country_code: str,
    overrides: NameOverrides,
    variant: ChineseVariant = "hans",
) -> str:
    for suffix in overrides.strip_suffixes.get(country_code, ()):
        converted = to_variant(suffix, variant)
        if value.endswith(converted) and len(value) > len(converted):
            return value[: -len(converted)]
    return value
