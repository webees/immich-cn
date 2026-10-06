from __future__ import annotations

from pathlib import Path

import pytest

from immich_cn.errors import ConfigError
from immich_cn.localization import (
    ChineseNameIndex,
    NameOverrides,
    build_name_index,
    has_cjk,
    is_japanese_language,
    language_rank,
    pick_from_alternates,
    to_variant,
)


def test_overrides_rejects_malformed_admin_code(tmp_path: Path) -> None:
    """[admins] 键写错会变成永远匹配不到的死条目，必须在加载时报错。"""
    path = tmp_path / "overrides.toml"
    path.write_text('[admins]\n"cn.02" = "浙江省"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="行政区代码"):
        NameOverrides.load(path)


def test_overrides_rejects_non_chinese_value_for_chinese_region(tmp_path: Path) -> None:
    """中文地区的覆盖值必须是中文名，否则等于把外文名写进发布产物。"""
    path = tmp_path / "overrides.toml"
    path.write_text('[admins]\n"CN.02" = "Zhejiang"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="不含中文"):
        NameOverrides.load(path)


def test_overrides_rejects_malformed_country_code(tmp_path: Path) -> None:
    path = tmp_path / "overrides.toml"
    path.write_text('[countries]\n"CHN" = "中国"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="alpha-2"):
        NameOverrides.load(path)


def test_shipped_overrides_pass_validation() -> None:
    """仓库自带的覆盖表必须通过新校验，且新补的条目确实生效。"""
    shipped = Path(__file__).resolve().parent.parent / "config" / "overrides.toml"
    overrides = NameOverrides.load(shipped)

    assert overrides.admins["MO.11875154"] == "花地玛堂区"
    assert overrides.admins["CN.23.12324204.1816914.1790964"] == "吴淞区"


def test_language_rank_prefers_simplified() -> None:
    assert language_rank("zh-Hans") < language_rank("zh-Hant")
    assert language_rank("zh-CN") < language_rank("zh-TW")
    assert language_rank("en") is None


def test_language_rank_handles_region_suffix() -> None:
    assert language_rank("zh-Hant-HK") is not None


def test_japanese_language_rejects_prefix_collisions() -> None:
    assert is_japanese_language("ja")
    assert is_japanese_language("ja-JP")
    assert not is_japanese_language("jam")


def test_to_variant_converts_traditional_to_simplified() -> None:
    assert to_variant("臺灣省", "hans") == "台湾省"


def test_has_cjk() -> None:
    assert has_cjk("东京都")
    assert not has_cjk("Tokyo")


def test_pick_from_alternates_prefers_chinese_only() -> None:
    assert pick_from_alternates(["Suzhou", "苏州市"]) == "苏州市"
    assert pick_from_alternates(["Suzhou"]) is None


def test_build_name_index_prefers_higher_priority_language() -> None:
    records = iter(
        [
            (1, "zh-Hant", "臺北市", False, False),
            (1, "zh-Hans", "台北市", False, False),
            (1, "en", "Taipei", True, False),
        ]
    )
    index = build_name_index(records, overrides=NameOverrides())
    # 同时断言“原始选择”本身：只比较 get() 会被繁简转换掩盖（假通过）
    assert index.names[1] == "台北市"
    assert index.get(1) == "台北市"


def test_build_name_index_prefers_preferred_name_within_language() -> None:
    records = iter(
        [
            (1, "zh", "旧称", False, False),
            (1, "zh", "北京市", True, False),
        ]
    )
    index = build_name_index(records, overrides=NameOverrides())
    assert index.names[1] == "北京市"


def test_build_name_index_ignores_historic_names() -> None:
    index = build_name_index(iter([(1, "zh", "旧名", False, True)]), overrides=NameOverrides())
    assert index.get(1) is None


def test_build_name_index_ignores_historic_japanese_names() -> None:
    index = build_name_index(iter([(1, "ja", "旧東京", False, True)]), overrides=NameOverrides())
    assert index.get_kanji(1) is None


def test_build_name_index_prefers_preferred_kanji_name() -> None:
    records = iter(
        [
            (1, "ja", "東京市", False, False),
            (1, "ja", "東京都", True, False),
        ]
    )
    index = build_name_index(records, overrides=NameOverrides())
    assert index.get_kanji(1) == "东京都"


def test_build_name_index_keeps_only_japanese_cjk_names() -> None:
    records = iter(
        [
            (1, "ja", "東京都", True, False),
            (2, "ja", "Tokyo", True, False),
            (3, "jam", "東京", True, False),
            (4, "ja-JP", "大阪府", False, False),
        ]
    )
    index = build_name_index(records, overrides=NameOverrides())
    assert index.get_kanji(1) == "东京都"
    assert index.get_kanji(2) is None
    assert index.get_kanji(3) is None
    assert index.get_kanji(4) == "大阪府"


def test_name_overrides_win(tmp_path: Path) -> None:
    path = tmp_path / "overrides.toml"
    path.write_text(
        "\n".join(
            [
                "[places]",
                '1816670 = "北京"',
                "[admins]",
                '"CN.22" = "北京市"',
                "[countries]",
                'CN = "中国"',
            ]
        ),
        encoding="utf-8",
    )
    overrides = NameOverrides.load(path)
    index = ChineseNameIndex(overrides=overrides)
    assert index.get(1816670) == "北京"
    assert index.get_admin("CN.22") == "北京市"
    assert index.get_country("cn") == "中国"


def test_traditional_variant_outputs_traditional() -> None:
    index = ChineseNameIndex(names={1: "台北市"}, variant="hant")
    assert index.get(1) == "臺北市"


def test_historical_country_overrides_are_present() -> None:
    overrides = NameOverrides.load(Path(__file__).resolve().parent.parent / "config" / "overrides.toml")
    assert overrides.countries["CS"] == "塞尔维亚和黑山"
    assert overrides.countries["AN"] == "荷属安的列斯"
