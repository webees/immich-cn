from __future__ import annotations

from pathlib import Path

import pytest

from immich_cn.errors import ConfigError
from immich_cn.localization import (
    LANGUAGE_PRIORITY,
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


def test_overrides_rejects_non_table_section(tmp_path: Path) -> None:
    """段写成标量时加载会崩在 .items()，必须报出可处理的配置错误。"""
    path = tmp_path / "overrides.toml"
    path.write_text("countries = 5\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=r"\[countries\] 必须是表"):
        NameOverrides.load(path)


def test_overrides_rejects_malformed_strip_suffixes(tmp_path: Path) -> None:
    """[rules.strip_suffixes] 值写错会静默不裁剪后缀，必须在加载时报错。"""
    path = tmp_path / "overrides.toml"
    path.write_text('[rules.strip_suffixes]\nJP = "都"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="非空字符串列表"):
        NameOverrides.load(path)


def test_overrides_normalizes_strip_suffix_keys(tmp_path: Path) -> None:
    """小写国家码按 [countries] 的口径规范为大写，否则是永远匹配不到的死条目。"""
    path = tmp_path / "overrides.toml"
    path.write_text('[rules.strip_suffixes]\njp = ["都"]\n', encoding="utf-8")

    assert NameOverrides.load(path).strip_suffixes["JP"] == ("都",)


def test_overrides_rejects_malformed_hk_district(tmp_path: Path) -> None:
    """[rules.hk_districts] 值不是字符串时会写出错乱的第三级区域名。"""
    path = tmp_path / "overrides.toml"
    path.write_text('[rules.hk_districts]\n"中西区" = 3\n', encoding="utf-8")

    with pytest.raises(ConfigError, match=r"\[rules\.hk_districts\].中西区 必须是非空字符串"):
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


def test_build_name_index_keeps_first_name_when_score_ties() -> None:
    """同语言同 preferred 时按上游行序取先者；后来的同分名称不得覆盖已选结果。"""
    records = iter(
        [
            (1, "zh", "北京市", False, False),
            (1, "zh", "北京", False, False),
        ]
    )
    index = build_name_index(records, overrides=NameOverrides())
    assert index.names[1] == "北京市"


def test_language_rank_treats_unknown_zh_prefix_as_lowest_priority() -> None:
    """`zho` 这类带 zh 前缀但不属于白名单的标签仍是候选，但排在所有白名单标签之后。"""
    assert language_rank("zho") == len(LANGUAGE_PRIORITY)
    assert language_rank("zh-yue") == LANGUAGE_PRIORITY.index("zh")
    assert language_rank("yue") is None


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
