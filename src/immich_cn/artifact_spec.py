"""制品命名规范 v4：项目命名空间只出现一次。"""

from __future__ import annotations

import re
from typing import Any

from immich_cn.display import pattern_keys
from immich_cn.errors import ConfigError

ARTIFACT_ID_PATTERN = re.compile(r"^immich-cn\.geodata\.[a-z0-9-]+\.(default|full)\.v[0-9]+$")
CANONICAL_FILE_PATTERN = re.compile(r"^immich-cn-geodata-[a-z0-9-]+-(default|full)-v[0-9]+\.zip$")
MANIFEST_FILE = "immich-cn-manifest-json-v1.json"
CHECKSUMS_FILE = "immich-cn-checksums-sha256-v1.txt"
PATTERNS_FILE = "immich-cn-patterns-tsv-v1.gz"
I18N_FILE = "immich-cn-i18n-json-v1.zip"
DATASET_FILE = "immich-cn-dataset-sqlite-v1.zip"
DATASET_MEMBER = "immich-cn-dataset-v1.sqlite"


def profile_id(pattern: str) -> str:
    """把展示 pattern 转成稳定 profile ID，例如 ``{admin_2} {admin_3}`` -> ``admin2-admin3``。"""
    keys = pattern_keys(pattern)
    if not keys:
        raise ConfigError(f"无法为 {pattern!r} 生成 profile ID")
    return "-".join(key.replace("admin_", "admin") for key in keys)


def scope_name(full: bool) -> str:
    return "full" if full else "default"


def artifact_id(pattern: str, full: bool, *, schema_version: int = 1) -> str:
    return f"immich-cn.geodata.{profile_id(pattern)}.{scope_name(full)}.v{schema_version}"


def canonical_filename(pattern: str, full: bool, *, schema_version: int = 1) -> str:
    return f"immich-cn-geodata-{profile_id(pattern)}-{scope_name(full)}-v{schema_version}.zip"


def validate_artifact_id(value: str) -> bool:
    return bool(ARTIFACT_ID_PATTERN.fullmatch(value))


def validate_canonical_filename(value: str) -> bool:
    return bool(CANONICAL_FILE_PATTERN.fullmatch(value))


def resolve_artifact(
    manifest: dict[str, Any],
    *,
    artifact_id: str | None = None,
    profile: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """从 v4 manifest 解析一个 canonical artifact。"""
    if manifest.get("artifactSpecVersion") != 4:
        raise ConfigError("manifest 的 artifactSpecVersion 不是 4")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ConfigError("manifest 没有 artifacts")
    candidates = [item for item in artifacts if isinstance(item, dict)]

    if artifact_id:
        matches = [item for item in candidates if item.get("id") == artifact_id]
    elif profile and scope:
        matches = [item for item in candidates if item.get("profile") == profile and item.get("scope") == scope]
    else:
        raise ConfigError("必须提供 --id 或同时提供 --profile/--scope")

    if not matches:
        raise ConfigError("没有匹配的 canonical artifact")
    if len(matches) > 1:
        raise ConfigError("匹配到多个 canonical artifact")
    return matches[0]
