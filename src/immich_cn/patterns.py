"""展示粒度（pattern）的定义与组合规则。"""

from __future__ import annotations

import re

from immich_cn.errors import ConfigError

_PLACEHOLDER = re.compile(r"\{([a-z0-9_]+)\}")

ALLOWED_KEYS = frozenset({"country", "admin_1", "admin_2", "admin_3", "admin_4"})


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
    try:
        rendered = pattern.format(**{key: levels.get(key, "") for key in ALLOWED_KEYS})
    except (KeyError, IndexError) as error:  # pragma: no cover - validate_pattern 已挡住
        raise ConfigError(f"无法渲染展示粒度 {pattern!r}：{error}") from error

    tokens = [token for token in rendered.replace("\u3000", " ").split(" ") if token]
    deduped: list[str] = []
    for token in tokens:
        if deduped and deduped[-1] == token:
            continue
        deduped.append(token)
    return " ".join(deduped)
