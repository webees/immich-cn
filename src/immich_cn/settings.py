"""构建配置与上游数据源清单。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from immich_cn import __version__
from immich_cn.display import validate_pattern
from immich_cn.errors import ConfigError

GEONAMES_BASE = "https://download.geonames.org/export/dump"
NATURAL_EARTH_VERSION = "v5.1.2"
NATURAL_EARTH_URL = (
    f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{NATURAL_EARTH_VERSION}"
    "/geojson/ne_10m_admin_0_countries.geojson"
)
I18N_ISO_COUNTRIES_VERSION = "7.0.0"
I18N_ISO_COUNTRIES_URL = (
    f"https://registry.npmjs.org/i18n-iso-countries/-/i18n-iso-countries-{I18N_ISO_COUNTRIES_VERSION}.tgz"
)

USER_AGENT = f"immich-cn/{__version__} (+https://github.com/webees/immich-cn)"


def positive_int_env(name: str, default: int) -> int:
    """读取必须大于 0 的整数环境变量。"""
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{name} 必须是整数：{raw!r}") from error
    if value < 1:
        raise ConfigError(f"{name} 必须大于 0：{value}")
    return value


def country_codes_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """读取逗号分隔的国家或地区代码，统一去空白并转大写。"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return tuple(item.strip().upper() for item in raw.split(",") if item.strip()) or default


#: 默认需要附带国家全量 dump 的地区；`cities500` 只有人口 > 500 的记录，国内数据在人口维度并不可靠。
DEFAULT_EXTRA_COUNTRIES: tuple[str, ...] = ("CN", "HK", "TW", "MO", "JP")

#: 需要"直辖市细化到区"的特殊二级行政代码，非 full 模式下也会保留。
FINE_GRAINED_ADMIN2: frozenset[str] = frozenset(
    {
        "CN.22.11876380",  # 北京市
        "CN.23.12324204",  # 上海市
        "CN.28.12324202",  # 天津市
        "CN.33.8739734",  # 重庆市
    }
)

#: 展示粒度变体，顺序即发布顺序。
DEFAULT_PATTERNS: tuple[str, ...] = (
    "{admin_2}",
    "{admin_3}",
    "{admin_4}",
    "{admin_2} {admin_3}",
    "{admin_2} {admin_4}",
    "{admin_3} {admin_4}",
    "{admin_2} {admin_3} {admin_4}",
)

#: 默认发布变体的 slug（immich-cn-geodata-admin2-default-v1.zip 指向它）。
DEFAULT_PATTERN = "{admin_2}"

ProviderName = Literal["offline", "amap", "nominatim", "auto"]
ChineseVariant = Literal["hans", "hant"]


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """一个上游数据源文件。"""

    name: str
    url: str
    filename: str
    #: 下载后在缓存目录中使用的文件名；默认与 filename 相同。
    download_name: str = ""
    #: 下载后需要从归档中解出的成员（zip/tar）；为空表示文件本身即最终产物。
    members: tuple[str, ...] = ()
    optional: bool = False
    #: 固定版本的产物应给出期望摘要；滚动数据保持为空。
    expected_sha256: str | None = None

    @property
    def is_archive(self) -> bool:
        return bool(self.members)

    @property
    def cache_filename(self) -> str:
        return self.download_name or self.filename


def geonames_sources(extra_countries: tuple[str, ...] = DEFAULT_EXTRA_COUNTRIES) -> list[SourceSpec]:
    """返回一次完整构建需要的 GeoNames 数据源。"""
    sources = [
        SourceSpec(
            name="cities500",
            url=f"{GEONAMES_BASE}/cities500.zip",
            filename="cities500.txt",
            download_name="cities500.zip",
            members=("cities500.txt",),
        ),
        SourceSpec(
            name="admin1CodesASCII",
            url=f"{GEONAMES_BASE}/admin1CodesASCII.txt",
            filename="admin1CodesASCII.txt",
        ),
        SourceSpec(
            name="admin2Codes",
            url=f"{GEONAMES_BASE}/admin2Codes.txt",
            filename="admin2Codes.txt",
        ),
        SourceSpec(
            name="countryInfo",
            url=f"{GEONAMES_BASE}/countryInfo.txt",
            filename="countryInfo.txt",
        ),
        SourceSpec(
            name="alternateNamesV2",
            url=f"{GEONAMES_BASE}/alternateNamesV2.zip",
            filename="alternateNamesV2.txt",
            download_name="alternateNamesV2.zip",
            members=("alternateNamesV2.txt",),
        ),
    ]
    for country in extra_countries:
        sources.append(
            SourceSpec(
                name=f"country_dump_{country}",
                url=f"{GEONAMES_BASE}/{country}.zip",
                filename=f"{country}.txt",
                download_name=f"{country}.zip",
                members=(f"{country}.txt", "readme.txt"),
                optional=True,
            )
        )
    return sources


def natural_earth_source() -> SourceSpec:
    return SourceSpec(
        name="naturalEarthCountries",
        url=NATURAL_EARTH_URL,
        filename="ne_10m_admin_0_countries.geojson",
        # v5.1.2 标签下的文件内容不可变，固定摘要防止上游被替换
        expected_sha256="239eec57ac17f100a11e2536cffc56752c318b50ae765b0918ff7aab4ce8f255",
    )


def i18n_sources() -> list[SourceSpec]:
    return [
        SourceSpec(
            name="i18nIsoCountries",
            url=I18N_ISO_COUNTRIES_URL,
            filename="i18n-iso-countries.tgz",
            members=("package/langs/",),
            # npm 同一版本不可重新发布，固定摘要可防供应链替换
            expected_sha256="44c38df798564ade0ee1e0b0b0161a2bfb741cd5cc739ba230184d6e6afd55cb",
        )
    ]


@dataclass(slots=True)
class BuildOptions:
    """来自 CLI 的构建设置，以及据此推导的路径。"""

    work_dir: Path = Path("build")
    dist_dir: Path = Path("dist")
    cache_dir: Path = Path(".cache/immich-cn")
    config_dir: Path = Path("config")
    extra_countries: tuple[str, ...] = DEFAULT_EXTRA_COUNTRIES
    patterns: tuple[str, ...] = DEFAULT_PATTERNS
    min_population: int = 100
    provider: ProviderName = "offline"
    chinese_variant: ChineseVariant = "hans"
    force_refresh: bool = False
    #: 使用 ETag/Last-Modified 校验上游是否更新；每日自动更新时应开启。
    revalidate: bool = False
    keep_raw: bool = False
    skip_fetch: bool = False
    jobs: int = field(default_factory=lambda: max(1, min(8, (os.cpu_count() or 2))))

    def __post_init__(self) -> None:
        if self.jobs < 0:
            raise ConfigError("jobs 不能为负数")
        if self.min_population < 0:
            raise ConfigError("min_population 不能为负数")
        if not self.patterns:
            raise ConfigError("至少需要一个展示粒度变体")
        for pattern in self.patterns:
            validate_pattern(pattern)

    @property
    def sources_dir(self) -> Path:
        return self.work_dir / "sources"

    @property
    def geodata_dir(self) -> Path:
        return self.work_dir / "geodata"

    def ensure_dirs(self) -> None:
        for path in (self.work_dir, self.dist_dir, self.cache_dir, self.sources_dir):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def amap_api_key(self) -> str | None:
        key = os.environ.get("AMAP_API_KEY", "").strip()
        return key or None

    def resolve_provider(self) -> ProviderName:
        """把 ``auto`` 解析为实际 provider。"""
        if self.provider != "auto":
            return self.provider
        return "amap" if self.amap_api_key else "offline"
