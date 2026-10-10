"""发布指纹：用于判断上游数据、构建配置或发布器是否发生变化。

指纹只覆盖"会影响产物内容"的部分：上游文件内容摘要、构建配置、构建器版本、
CI 修订与 manifest schema。时间戳、构建机器等信息不参与计算。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _sources(manifest: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = manifest.get("sources")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError("manifest.sources 必须是数组")
    if not raw:
        raise ValueError("manifest.sources 不能为空")
    entries: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"manifest.sources[{index}] 必须是对象")
        name = item.get("name")
        sha256 = item.get("sha256")
        if not isinstance(name, str) or not name:
            raise ValueError(f"manifest.sources[{index}].name 必须是非空字符串")
        if not isinstance(sha256, str) or not sha256:
            raise ValueError(f"manifest.sources[{index}].sha256 必须是非空字符串")
        entries.append({"name": name, "sha256": sha256})
    return sorted(entries, key=lambda entry: entry["name"])


def _config(manifest: Mapping[str, Any]) -> dict[str, Any]:
    raw = manifest.get("config")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _tool(manifest: Mapping[str, Any]) -> dict[str, str]:
    raw = manifest.get("tool")
    if not isinstance(raw, Mapping):
        return {}
    return {key: str(raw.get(key, "")) for key in ("name", "version", "revision")}


def data_fingerprint(manifest: Mapping[str, Any]) -> str:
    """返回 manifest 的发布指纹（sha256 十六进制）。

    指纹还覆盖构建器版本、CI 修订和 manifest schema，避免只改构建逻辑、
    不改上游文件与构建配置时被误判为“无变化”而跳过发布。
    """
    payload = {
        "schemaVersion": manifest.get("schemaVersion"),
        "sources": _sources(manifest),
        "config": _config(manifest),
        "tool": _tool(manifest),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint_from_file(path: str | Path) -> str:
    """从 immich-cn-manifest-json-v1.json 文件读取并计算指纹。"""
    manifest_path = Path(path)
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, Mapping):
        raise ValueError(f"{path} 不是合法的 manifest")
    return data_fingerprint(manifest)
