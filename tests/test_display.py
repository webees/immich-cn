from __future__ import annotations

import pytest

from immich_cn.display import (
    ALLOWED_KEYS,
    compose,
    normalize_level,
    pattern_keys,
    slugify,
    validate_pattern,
)
from immich_cn.errors import ConfigError


def test_compose_deduplicates_adjacent_levels() -> None:
    assert compose("{admin_2} {admin_3}", {"admin_2": "苏州市", "admin_3": "苏州市"}) == "苏州市"


def test_compose_joins_multiple_levels() -> None:
    levels = {"admin_2": "苏州市", "admin_3": "昆山市", "admin_4": "周市镇"}
    assert compose("{admin_2} {admin_3} {admin_4}", levels) == "苏州市 昆山市 周市镇"


def test_compose_skips_empty_levels() -> None:
    assert compose("{admin_2} {admin_4}", {"admin_2": "苏州市", "admin_4": ""}) == "苏州市"


def test_compose_deduplicates_identical_multi_token_levels() -> None:
    levels = {"admin_2": "株洲 市", "admin_3": "株洲 市", "admin_4": "株洲 市"}
    assert compose("{admin_2} {admin_3} {admin_4}", levels) == "株洲市"


def test_compose_keeps_all_distinct_levels() -> None:
    levels = {"admin_2": "上海市", "admin_3": "嘉定区", "admin_4": "嘉定镇"}
    assert compose("{admin_2} {admin_3} {admin_4}", levels) == "上海市 嘉定区 嘉定镇"


def test_normalize_level_removes_cjk_inner_spaces() -> None:
    assert normalize_level("株洲\u3000市") == "株洲市"
    assert normalize_level("New   York") == "New York"


def test_normalize_level_keeps_space_next_to_non_cjk() -> None:
    """只有两侧都是 CJK 时才去掉空格；中英混排的空格必须保留。

    只测「株洲 市」区分不了「左侧是 CJK」与「两侧都是 CJK」，
    会把「香港 Hong Kong」压成「香港Hong Kong」。
    """
    assert normalize_level("苏州市 A") == "苏州市 A"
    assert normalize_level("香港 Hong Kong") == "香港 Hong Kong"
    assert normalize_level("A 苏州市") == "A 苏州市"
    assert normalize_level("苏州市 昆山市") == "苏州市昆山市"


def test_pattern_keys_preserves_order() -> None:
    assert pattern_keys("{admin_3}-{admin_2}") == ("admin_3", "admin_2")


def test_slugify() -> None:
    assert slugify("{admin_2} {admin_3}") == "admin_2_admin_3"


@pytest.mark.parametrize("pattern", ["", "{}", "admin_2", "{unknown}", "{country}"])
def test_validate_pattern_rejects_invalid(pattern: str) -> None:
    with pytest.raises(ConfigError):
        validate_pattern(pattern)


@pytest.mark.parametrize("pattern", ["", "{country}"])
def test_validate_pattern_error_message_is_actionable(pattern: str) -> None:
    """拒绝原因必须指向 admin_N 占位符，便于用户立刻修正。"""
    with pytest.raises(ConfigError) as excinfo:
        validate_pattern(pattern)
    assert "admin_N" in str(excinfo.value)


def _reference_compose(pattern: str, levels: dict[str, str]) -> str:
    """优化前的实现，作为等价性基准保留在测试里。"""
    validate_pattern(pattern)
    normalized = {key: normalize_level(levels.get(key, "")) for key in ALLOWED_KEYS}
    level_values: dict[str, str] = {}
    previous = ""
    for key in pattern_keys(pattern):
        value = normalized.get(key, "")
        if value and value == previous:
            value = ""
        level_values[key] = value
        if value:
            previous = value
    rendered = pattern.format(**{**normalized, **level_values})
    unique: list[str] = []
    for token in rendered.split():
        if unique and unique[-1] == token:
            continue
        unique.append(token)
    return " ".join(unique)


LEVEL_SAMPLES: tuple[dict[str, str], ...] = (
    {"country": "CN", "admin_1": "江苏省", "admin_2": "苏州市", "admin_3": "昆山市", "admin_4": "周市镇"},
    {"country": "CN", "admin_1": "湖南省", "admin_2": "株洲 市", "admin_3": "株洲 市", "admin_4": "株洲 市"},
    {"country": "HK", "admin_1": "香港", "admin_2": "元朗区", "admin_3": "新界 元朗区", "admin_4": ""},
    {"country": "US", "admin_1": "New York", "admin_2": "New York County", "admin_3": "", "admin_4": ""},
    {"country": "CN", "admin_1": "上海市", "admin_2": "上海市", "admin_3": "", "admin_4": ""},
    {"country": "", "admin_1": "", "admin_2": "", "admin_3": "", "admin_4": ""},
    {"country": "CN", "admin_1": "北京市", "admin_2": "北京市", "admin_3": "朝阳区", "admin_4": "三里屯街道"},
)


@pytest.mark.parametrize(
    "pattern",
    [
        "{admin_2}",
        "{admin_3}",
        "{admin_4}",
        "{admin_2} {admin_3}",
        "{admin_2} {admin_4}",
        "{admin_3} {admin_4}",
        "{admin_2} {admin_3} {admin_4}",
        "{admin_3}-{admin_2}",
        "{country}·{admin_1} {admin_2}",
    ],
)
def test_compose_matches_reference_implementation(pattern: str) -> None:
    """优化后的 compose 必须与优化前逐字节一致（防止为性能改坏语义）。"""
    for levels in LEVEL_SAMPLES:
        assert compose(pattern, levels) == _reference_compose(pattern, levels), (pattern, levels)
