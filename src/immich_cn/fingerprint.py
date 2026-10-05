"""数据指纹：用于判断上游数据或构建配置是否发生变化。

指纹只覆盖"会影响产物内容"的部分：上游文件内容摘要与构建配置。
时间戳、构建机器等信息不参与计算，因此同一份数据在任意时刻构建都会得到相同指纹。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _sources(manifest: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = manifest.get("sources")
    if not isinstance(raw, Sequence):
        return []
    entries: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        entries.append({"name": str(item.get("name", "")), "sha256": str(item.get("sha256", ""))})
    return sorted(entries, key=lambda entry: entry["name"])


def _config(manifest: Mapping[str, Any]) -> dict[str, Any]:
    raw = manifest.get("config")
    return dict(raw) if isinstance(raw, Mapping) else {}


def data_fingerprint(manifest: Mapping[str, Any]) -> str:
    """返回 manifest 的数据指纹（sha256 十六进制）。"""
    payload = {
        "sources": _sources(manifest),
        "config": _config(manifest),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint_from_file(path: str | Path) -> str:
    """从 manifest.json 文件读取并计算指纹。"""
    manifest_path = Path(path)
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, Mapping):
        raise ValueError(f"{path} 不是合法的 manifest")
    return data_fingerprint(manifest)
