from __future__ import annotations

import pytest

from immich_cn.errors import ConfigError
from immich_cn.patterns import compose, pattern_keys, slugify, validate_pattern


def test_compose_deduplicates_adjacent_levels() -> None:
    assert compose("{admin_2} {admin_3}", {"admin_2": "苏州市", "admin_3": "苏州市"}) == "苏州市"


def test_compose_joins_multiple_levels() -> None:
    levels = {"admin_2": "苏州市", "admin_3": "昆山市", "admin_4": "周市镇"}
    assert compose("{admin_2} {admin_3} {admin_4}", levels) == "苏州市 昆山市 周市镇"


def test_compose_skips_empty_levels() -> None:
    assert compose("{admin_2} {admin_4}", {"admin_2": "苏州市", "admin_4": ""}) == "苏州市"


def test_pattern_keys_preserves_order() -> None:
    assert pattern_keys("{admin_3}-{admin_2}") == ("admin_3", "admin_2")


def test_slugify() -> None:
    assert slugify("{admin_2} {admin_3}") == "admin_2_admin_3"


@pytest.mark.parametrize("pattern", ["admin_2", "{unknown}", "{country}"])
def test_validate_pattern_rejects_invalid(pattern: str) -> None:
    with pytest.raises(ConfigError):
        validate_pattern(pattern)
