"""展示粒度（pattern）的定义与组合规则。"""

from __future__ import annotations

import re
from functools import lru_cache

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


@lru_cache(maxsize=64)
def pattern_keys(pattern: str) -> tuple[str, ...]:
    """返回 pattern 中出现的占位符，保持出现顺序。"""
    return tuple(_PLACEHOLDER.findall(pattern))


def validate_pattern(pattern: str) -> None:
    _validate_keys(pattern, pattern_keys(pattern))


def _validate_keys(pattern: str, keys: tuple[str, ...]) -> None:
    """校验占位符；与 :func:`validate_pattern` 等价，但可复用已解析的 keys。"""
    # 注意：keys 为空时下面的 admin_N 检查同样会拒绝，
    # 因此这里不再保留一个永远排不上用场的“无占位符”分支。
    unknown = [key for key in keys if key not in ALLOWED_KEYS]
    if unknown:
        raise ConfigError(f"展示粒度 {pattern!r} 含未知占位符：{', '.join(unknown)}")
    duplicates = [key for key in dict.fromkeys(keys) if keys.count(key) > 1]
    if duplicates:
        raise ConfigError(f"展示粒度 {pattern!r} 含重复占位符：{', '.join(duplicates)}")
    if "admin_2" not in keys and "admin_3" not in keys and "admin_4" not in keys:
        raise ConfigError(f"展示粒度 {pattern!r} 至少要包含一个 admin_N 占位符")


def slugify(pattern: str) -> str:
    """``{admin_2} {admin_3}`` → ``admin_2_admin_3``。"""
    keys = pattern_keys(pattern)
    if not keys:
        raise ConfigError(f"无法为 {pattern!r} 生成 slug")
    return "_".join(keys)


def compose(pattern: str, levels: dict[str, str]) -> str:
    """按 pattern 组合展示名，并去掉相邻重复与多余空白。

    打包阶段会调用上千万次（行数 × 变体数），因此这里只做必要工作：
    ``pattern_keys`` 带缓存，取值字典只包含 pattern 中出现的键。
    """
    keys = pattern_keys(pattern)
    _validate_keys(pattern, keys)

    # 层级相同（例如苏州市的 admin_2 与 admin_3）时只保留一次。
    values: dict[str, str] = {}
    previous = ""
    for key in keys:
        value = normalize_level(levels.get(key, ""))
        if value and value == previous:
            value = ""
        values[key] = value
        if value:
            previous = value

    try:
        rendered = pattern.format(**values)
    except (KeyError, IndexError) as error:  # pragma: no cover - validate_pattern 已挡住
        raise ConfigError(f"无法渲染展示粒度 {pattern!r}：{error}") from error

    tokens = rendered.split()
    unique_tokens: list[str] = []
    for token in tokens:
        if unique_tokens and unique_tokens[-1] == token:
            continue
        unique_tokens.append(token)
    return " ".join(unique_tokens)
