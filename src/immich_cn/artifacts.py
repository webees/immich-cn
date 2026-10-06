"""制品命名规范 v2。

文件名是兼容层；manifest 中的 canonical ID 才是机器可读契约。
"""

from __future__ import annotations

import re
from typing import Any

from immich_cn.errors import ConfigError
from immich_cn.patterns import pattern_keys

ARTIFACT_ID_PATTERN = re.compile(r"^geodata\.immich\.[a-z0-9-]+\.(default|full)\.v[0-9]+$")
CANONICAL_FILE_PATTERN = re.compile(r"^immich-cn-geodata-immich-[a-z0-9-]+-(default|full)-v[0-9]+\.zip$")


def profile_id(pattern: str) -> str:
    """把展示 pattern 转成稳定 profile ID，例如 ``{admin_2} {admin_3}`` -> ``admin2-admin3``。"""
    keys = pattern_keys(pattern)
    if not keys:
        raise ConfigError(f"无法为 {pattern!r} 生成 profile ID")
    return "-".join(key.replace("admin_", "admin") for key in keys)


def scope_name(full: bool) -> str:
    return "full" if full else "default"


def artifact_id(pattern: str, full: bool, *, schema_version: int = 1) -> str:
    return f"geodata.immich.{profile_id(pattern)}.{scope_name(full)}.v{schema_version}"


def canonical_filename(pattern: str, full: bool, *, schema_version: int = 1) -> str:
    return f"immich-cn-geodata-immich-{profile_id(pattern)}-{scope_name(full)}-v{schema_version}.zip"


def validate_artifact_id(value: str) -> bool:
    return bool(ARTIFACT_ID_PATTERN.fullmatch(value))


def validate_canonical_filename(value: str) -> bool:
    return bool(CANONICAL_FILE_PATTERN.fullmatch(value))


def resolve_artifact(
    manifest: dict[str, Any],
    *,
    artifact_id: str | None = None,
    alias: str | None = None,
    profile: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """从 v2 manifest 解析一个 canonical artifact。"""
    if manifest.get("artifactSpecVersion") != 2:
        raise ConfigError("manifest 的 artifactSpecVersion 不是 2")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ConfigError("manifest 没有 artifacts")
    candidates = [item for item in artifacts if isinstance(item, dict)]

    if alias:
        aliases = manifest.get("aliases")
        legacy_aliases = manifest.get("legacyAliases")
        combined: dict[str, object] = {}
        if isinstance(aliases, dict):
            combined.update(aliases)
        if isinstance(legacy_aliases, dict):
            combined.update(legacy_aliases)
        if alias not in combined:
            raise ConfigError(f"manifest 中没有 alias：{alias}")
        artifact_id = str(combined[alias])

    if artifact_id:
        matches = [item for item in candidates if item.get("id") == artifact_id]
    elif profile and scope:
        matches = [item for item in candidates if item.get("profile") == profile and item.get("scope") == scope]
    else:
        raise ConfigError("必须提供 --id、--alias 或同时提供 --profile/--scope")

    if not matches:
        raise ConfigError("没有匹配的 canonical artifact")
    if len(matches) > 1:
        raise ConfigError("匹配到多个 canonical artifact")
    return matches[0]
