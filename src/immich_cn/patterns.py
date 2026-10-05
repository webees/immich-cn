"""展示粒度（pattern）的定义与组合规则。"""

from __future__ import annotations

import re

from immich_cn.errors import ConfigError

_PLACEHOLDER = re.compile(r"\{([a-z0-9_]+)\}")

ALLOWED_KEYS = frozenset({"country", "admin_1", "admin_2", "admin_3", "admin_4"})

_CJK_RANGES = (
    ("\u3400", "\u4dbf"),
    ("\u4e00", "\u9fff"),
    ("\uf900", "\ufaff"),
)


def _is_cjk(char: str) -> bool:
    return any(low <= char <= high for low, high in _CJK_RANGES)


def normalize_level(value: str) -> str:
    """规范化单个层级名称。

    - 全角空格与连续空白折叠为单个半角空格；
    - 去掉中日韩字符之间的空格（GeoNames 中存在 ``株洲 市`` 这类写法）。
    """
    collapsed = " ".join(value.replace("\u3000", " ").split())
    if " " not in collapsed:
        return collapsed

    result: list[str] = []
    for index, char in enumerate(collapsed):
        if (
            char == " "
            and 0 < index < len(collapsed) - 1
            and _is_cjk(collapsed[index - 1])
            and _is_cjk(collapsed[index + 1])
        ):
            continue
        result.append(char)
    return "".join(result)


def pattern_keys(pattern: str) -> tuple[str, ...]:
    """返回 pattern 中出现的占位符，保持出现顺序。"""
    return tuple(_PLACEHOLDER.findall(pattern))


def validate_pattern(pattern: str) -> None:
    keys = pattern_keys(pattern)
    if not keys:
        raise ConfigError(f"展示粒度 {pattern!r} 未包含任何占位符")
    unknown = [key for key in keys if key not in ALLOWED_KEYS]
    if unknown:
        raise ConfigError(f"展示粒度 {pattern!r} 含未知占位符：{', '.join(unknown)}")
    if "admin_2" not in keys and "admin_3" not in keys and "admin_4" not in keys:
        raise ConfigError(f"展示粒度 {pattern!r} 至少要包含一个 admin_N 占位符")


def slugify(pattern: str) -> str:
    """``{admin_2} {admin_3}`` → ``admin_2_admin_3``。"""
    keys = pattern_keys(pattern)
    if not keys:
        raise ConfigError(f"无法为 {pattern!r} 生成 slug")
    return "_".join(keys)


def compose(pattern: str, levels: dict[str, str]) -> str:
    """按 pattern 组合展示名，并去掉相邻重复与多余空白。"""
    validate_pattern(pattern)
    normalized = {key: normalize_level(levels.get(key, "")) for key in ALLOWED_KEYS}

    # 层级相同（例如苏州市的 admin_2 与 admin_3）时只保留一次。
    level_values: dict[str, str] = {}
    previous = ""
    for key in pattern_keys(pattern):
        value = normalized.get(key, "")
        if value and value == previous:
            value = ""
        level_values[key] = value
        if value:
            previous = value

    try:
        rendered = pattern.format(**{**normalized, **level_values})
    except (KeyError, IndexError) as error:  # pragma: no cover - validate_pattern 已挡住
        raise ConfigError(f"无法渲染展示粒度 {pattern!r}：{error}") from error

    tokens = rendered.split()
    unique_tokens: list[str] = []
    for token in tokens:
        if unique_tokens and unique_tokens[-1] == token:
            continue
        unique_tokens.append(token)
    return " ".join(unique_tokens)
