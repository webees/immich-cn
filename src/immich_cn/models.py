"""流水线内部使用的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field

# GeoNames 列索引（0 基），命名与 https://download.geonames.org/export/dump/readme.txt 一致。
GEO_COLUMNS = 19
IDX_GEONAMEID = 0
IDX_NAME = 1
IDX_ASCIINAME = 2
IDX_ALTERNATENAMES = 3
IDX_LATITUDE = 4
IDX_LONGITUDE = 5
IDX_FEATURE_CLASS = 6
IDX_FEATURE_CODE = 7
IDX_COUNTRY_CODE = 8
IDX_ADMIN1 = 10
IDX_ADMIN2 = 11
IDX_ADMIN3 = 12
IDX_ADMIN4 = 13
IDX_POPULATION = 14
IDX_MODIFICATION_DATE = 18


@dataclass(slots=True)
class Place:
    """一行 GeoNames places 记录（cities500.txt 或国家全量 dump）。"""

    columns: list[str]

    @classmethod
    def from_line(cls, line: str) -> Place | None:
        columns = line.rstrip("\r\n").split("\t")
        if len(columns) < GEO_COLUMNS:
            return None
        return cls(columns=columns)

    @property
    def geoname_id(self) -> int:
        return int(self.columns[IDX_GEONAMEID])

    @property
    def country_code(self) -> str:
        return self.columns[IDX_COUNTRY_CODE]

    @property
    def admin1_code(self) -> str:
        return self.columns[IDX_ADMIN1]

    @property
    def admin2_code(self) -> str:
        return self.columns[IDX_ADMIN2]

    @property
    def admin3_code(self) -> str:
        return self.columns[IDX_ADMIN3]

    @property
    def admin4_code(self) -> str:
        return self.columns[IDX_ADMIN4]

    @property
    def feature_class(self) -> str:
        return self.columns[IDX_FEATURE_CLASS]

    @property
    def feature_code(self) -> str:
        return self.columns[IDX_FEATURE_CODE]

    @property
    def population(self) -> int:
        raw = self.columns[IDX_POPULATION]
        try:
            return int(raw)
        except ValueError:
            return 0

    @property
    def location_key(self) -> tuple[str, str]:
        """(经度, 纬度) 字符串键，与历史数据保持一致。"""
        return (self.columns[IDX_LONGITUDE], self.columns[IDX_LATITUDE])

    @property
    def alternate_names(self) -> list[str]:
        raw = self.columns[IDX_ALTERNATENAMES]
        if not raw:
            return []
        return [item for item in raw.split(",") if item]

    def admin_chain(self) -> tuple[str, str, str, str]:
        return (self.admin1_code, self.admin2_code, self.admin3_code, self.admin4_code)

    def to_line(self) -> str:
        return "\t".join(self.columns)


@dataclass(frozen=True, slots=True)
class AdminEntry:
    """adminNCodes / 自建行政级别表中的一条记录。"""

    code: str
    name: str
    ascii_name: str
    geoname_id: int | None = None


@dataclass(slots=True)
class PlaceNames:
    """一个地点最终对外展示的四级中文名。"""

    geoname_id: int
    country: str = ""
    admin_1: str = ""
    admin_2: str = ""
    admin_3: str = ""
    admin_4: str = ""

    def levels(self) -> dict[str, str]:
        return {
            "country": self.country,
            "admin_1": self.admin_1,
            "admin_2": self.admin_2,
            "admin_3": self.admin_3,
            "admin_4": self.admin_4,
        }

    def fill_gaps(self) -> None:
        """低层级缺失时回退到上一级，避免出现空的展示名。"""
        if not self.admin_2:
            self.admin_2 = self.admin_1
        if not self.admin_3:
            self.admin_3 = self.admin_2
        if not self.admin_4:
            self.admin_4 = self.admin_3


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """一次构建实际使用的数据源指纹。"""

    name: str
    url: str
    sha256: str
    size_bytes: int
    etag: str | None = None
    last_modified: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "url": self.url,
            "sha256": self.sha256,
            "sizeBytes": self.size_bytes,
            "etag": self.etag,
            "lastModified": self.last_modified,
        }


@dataclass(frozen=True, slots=True)
class Variant:
    """一个可发布的展示粒度变体。"""

    pattern: str
    slug: str
    full: bool

    @property
    def filename(self) -> str:
        suffix = "_full" if self.full else ""
        return f"geodata_{self.slug}{suffix}.zip"


@dataclass(slots=True)
class BuildStats:
    """构建统计，写入 manifest 便于审计。"""

    source_places: int = 0
    extra_places: int = 0
    output_places: int = 0
    dropped_places: int = 0
    translated_names: int = 0
    fallback_names: int = 0
    admin1_entries: int = 0
    admin2_entries: int = 0
    admin3_entries: int = 0
    admin4_entries: int = 0
    per_country: dict[str, int] = field(default_factory=dict)

    def count_country(self, country_code: str) -> None:
        self.per_country[country_code] = self.per_country.get(country_code, 0) + 1

    def as_dict(self) -> dict[str, object]:
        return {
            "sourcePlaces": self.source_places,
            "extraPlaces": self.extra_places,
            "outputPlaces": self.output_places,
            "droppedPlaces": self.dropped_places,
            "translatedNames": self.translated_names,
            "fallbackNames": self.fallback_names,
            "adminEntries": {
                "admin1": self.admin1_entries,
                "admin2": self.admin2_entries,
                "admin3": self.admin3_entries,
                "admin4": self.admin4_entries,
            },
            "perCountry": dict(sorted(self.per_country.items())),
        }
