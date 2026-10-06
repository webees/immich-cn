"""构造最小但结构完整的 GeoNames 数据源，供单元测试与本地冒烟构建复用。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path


def geo_row(
    geoname_id: int,
    name: str,
    *,
    ascii_name: str | None = None,
    alternates: str = "",
    latitude: str = "0",
    longitude: str = "0",
    feature_class: str = "P",
    feature_code: str = "PPL",
    country: str = "CN",
    admin1: str = "",
    admin2: str = "",
    admin3: str = "",
    admin4: str = "",
    population: int = 0,
    modified: str = "2026-01-01",
) -> str:
    """按 GeoNames 19 列格式生成一行 places 数据。"""
    columns = [
        str(geoname_id),
        name,
        ascii_name or name,
        alternates,
        latitude,
        longitude,
        feature_class,
        feature_code,
        country,
        "",
        admin1,
        admin2,
        admin3,
        admin4,
        str(population),
        "",
        "",
        "Asia/Shanghai",
        modified,
    ]
    assert len(columns) == 19
    return "\t".join(columns)


def alternate_row(alt_id: int, geoname_id: int, language: str, name: str, *, preferred: bool = False) -> str:
    """按 alternateNamesV2 格式生成一行。"""
    fields = [
        str(alt_id),
        str(geoname_id),
        language,
        name,
        "1" if preferred else "",
        "",
        "",
        "",
        "",
        "",
    ]
    return "\t".join(fields)


def write_lines(path: Path, lines: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def create_synthetic_sources(work_dir: Path, langs_dir: Path) -> Path:
    """写出全部数据源，返回 sources 目录。"""
    sources = work_dir / "sources"

    write_lines(
        sources / "cities500.txt",
        [
            geo_row(
                1816670,
                "Beijing",
                alternates="北京,北京市,Beijing",
                latitude="39.9075",
                longitude="116.39723",
                feature_code="PPLA",
                admin1="22",
                admin2="11876380",
                population=11_716_620,
            ),
            geo_row(
                1886760,
                "Suzhou",
                alternates="苏州,苏州市,Suzhou",
                latitude="31.30408",
                longitude="120.59538",
                admin1="04",
                admin2="SZ",
                population=5_345_961,
            ),
            geo_row(
                1819729,
                "Hong Kong",
                alternates="香港,Hong Kong",
                latitude="22.28552",
                longitude="114.15769",
                country="HK",
                admin1="NYL",
                population=7_482_500,
            ),
            geo_row(
                1668341,
                "Taipei",
                alternates="台北,臺北,Taipei",
                latitude="25.04776",
                longitude="121.53185",
                country="TW",
                admin1="03",
                admin2="TPE",
                population=7_871_900,
            ),
            geo_row(
                5128581,
                "New York City",
                alternates="New York,纽约",
                latitude="40.71427",
                longitude="-74.00597",
                country="US",
                admin1="NY",
                admin2="061",
                population=8_804_190,
            ),
            # 缺少有效 admin1，应被过滤掉
            geo_row(9999999, "Ghost Town", latitude="1", longitude="1", admin1="ZZ", population=10),
        ],
    )

    write_lines(
        sources / "admin1CodesASCII.txt",
        [
            "CN.22\tBeijing\tBeijing\t1816670",
            "CN.04\tJiangsu\tJiangsu\t1806260",
            "HK.NYL\tYuen Long\tYuen Long\t1818224",
            "MO.11875154\tNossa Senhora de Fatima\tNossa Senhora de Fatima\t11875154",
            "TW.03\tTaipei\tTaipei\t7280290",
            "JP.01\tHokkaido\tHokkaido\t2130656",
            "US.NY\tNew York\tNew York\t5128638",
        ],
    )

    write_lines(
        sources / "admin2Codes.txt",
        [
            "CN.22.11876380\tBeijing\tBeijing\t11876380",
            "CN.04.SZ\tSuzhou Shi\tSuzhou Shi\t1886760",
            "TW.03.TPE\tTaipei City\tTaipei City\t1668338",
            "JP.01.01\t札幌市\tSapporo\t2130640",
            "US.NY.061\tNew York County\tNew York County\t5128594",
        ],
    )

    write_lines(
        sources / "countryInfo.txt",
        [
            "# GeoNames country info",
            "CN\tCHN\t156\tCH\tChina\tBeijing\t9596961\t1330044000\tAS\t.cn\tCNY\tYuan Renminbi\t86\t######\t^\\d{6}$\tzh-CN,yue,wuu\t1814991\t",
            "HK\tHKG\t344\tHK\tHong Kong\t\t1092\t6898686\tAS\t.hk\tHKD\tDollar\t852\t######\t\tzh-HK,en\t1819730\t",
            "TW\tTWN\t158\tTW\tTaiwan\tTaipei\t35980\t22894384\tAS\t.tw\tTWD\tDollar\t886\t#####\t\tzh-TW,zh-Hant\t1668284\t",
            "JP\tJPN\t392\tJA\tJapan\tTokyo\t377835\t127288000\tAS\t.jp\tJPY\tYen\t81\t###-####\t\tja\t1861060\t",
            "US\tUSA\t840\tUS\tUnited States\tWashington\t9629091\t310232863\tNA\t.us\tUSD\tDollar\t1\t#####-####\t\ten-US\t6252001\t",
            "CS\tSCG\t891\tCS\tSerbia and Montenegro\tBelgrade\t102350\t10829175\tEU\t.cs\tRSD\tDinar\t381\t######\t\tsr,hu,bs,sq,hr,ro\t8505033\t",
            "AN\tANT\t530\tAN\tNetherlands Antilles\tWillemstad\t960\t225369\tNA\t.an\tANG\tGuilder\t599\t######\t\tnl\t8505034\t",
        ],
    )

    write_lines(
        sources / "alternateNamesV2.txt",
        [
            alternate_row(1, 1816670, "zh", "北京市", preferred=True),
            alternate_row(2, 1816670, "en", "Beijing"),
            alternate_row(3, 1886760, "zh", "苏州市", preferred=True),
            alternate_row(4, 1886760, "zh-Hant", "蘇州市"),
            alternate_row(5, 1819729, "zh", "香港特別行政區", preferred=True),
            alternate_row(6, 1818224, "zh", "元朗區", preferred=True),
            alternate_row(7, 7280290, "zh-hant", "臺灣省", preferred=True),
            alternate_row(8, 1668338, "zh-hant", "臺北市", preferred=True),
            alternate_row(9, 1806260, "zh", "江苏省", preferred=True),
            alternate_row(10, 1886760, "zh-Hant", "蘇州市"),
            alternate_row(11, 9001, "zh", "昆山市", preferred=True),
            alternate_row(12, 9002, "zh", "周市镇", preferred=True),
            alternate_row(13, 5128638, "zh", "纽约州", preferred=True),
            alternate_row(14, 5128594, "zh", "纽约县", preferred=True),
            alternate_row(15, 1668284, "zh", "台湾", preferred=True),
            alternate_row(16, 1814991, "zh", "中国", preferred=True),
            alternate_row(17, 1819730, "zh", "香港", preferred=True),
            alternate_row(18, 1861060, "zh", "日本", preferred=True),
            alternate_row(19, 6252001, "zh", "美国", preferred=True),
            alternate_row(20, 11876380, "zh", "北京市", preferred=True),
            alternate_row(21, 7280290, "zh", "台湾省", preferred=True),
            alternate_row(22, 2130656, "zh", "北海道", preferred=True),
        ],
    )

    write_lines(
        sources / "CN.txt",
        [
            geo_row(
                9001,
                "Kunshan",
                alternates="昆山,昆山市",
                latitude="31.38",
                longitude="120.95",
                feature_class="A",
                feature_code="ADM3",
                admin1="04",
                admin2="SZ",
                admin3="KS",
                population=1_000_000,
            ),
            geo_row(
                9002,
                "Zhoushi",
                alternates="周市镇",
                latitude="31.44",
                longitude="120.94",
                feature_class="A",
                feature_code="ADM4",
                admin1="04",
                admin2="SZ",
                admin3="KS",
                admin4="ZSZ",
                population=50_000,
            ),
            # 不在 cities500 中的补充点位：非 full 变体也会保留（人口 >= 100）
            geo_row(
                9100,
                "Kunshan City",
                alternates="昆山",
                latitude="31.381",
                longitude="120.951",
                admin1="04",
                admin2="SZ",
                admin3="KS",
                admin4="ZSZ",
                population=500,
            ),
            # 人口为 0：只有 full 变体保留
            geo_row(
                9101,
                "Zhoushi Village",
                alternates="周市村",
                latitude="31.441",
                longitude="120.941",
                admin1="04",
                admin2="SZ",
                admin3="KS",
                admin4="ZSZ",
                population=0,
            ),
            # 与 cities500 完全重复（同 ID、同坐标）：必须被去重逻辑丢弃
            geo_row(
                1886760,
                "Suzhou",
                latitude="31.30408",
                longitude="120.59538",
                admin1="04",
                admin2="SZ",
                population=5_345_961,
            ),
            # 新 ID 但坐标与 cities500 已有点位相同：同样必须被丢弃
            geo_row(
                9200,
                "Suzhou Duplicate",
                latitude="31.30408",
                longitude="120.59538",
                admin1="04",
                admin2="SZ",
                population=999,
            ),
        ],
    )

    (sources / "ne_10m_admin_0_countries.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"ADMIN": "China", "ADM0_A3": "CHN"},
                        "geometry": {"type": "Point", "coordinates": [104.0, 35.0]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    langs_dir.mkdir(parents=True, exist_ok=True)
    (langs_dir / "zh.json").write_text(
        json.dumps(
            {
                "locale": "zh",
                "countries": {"CN": "中国", "HK": "中国香港", "TW": "中国台湾", "JP": "日本", "US": "美国"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (langs_dir / "en.json").write_text(
        json.dumps(
            {
                "locale": "en",
                "countries": {
                    "CN": "China",
                    "HK": "Hong Kong",
                    "TW": "Taiwan",
                    "JP": "Japan",
                    "US": "United States",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return sources
