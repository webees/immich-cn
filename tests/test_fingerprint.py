from __future__ import annotations

import json
from pathlib import Path

import pytest

from immich_cn.fingerprint import data_fingerprint, fingerprint_from_file


def make_manifest(**overrides: object) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "generatedAt": "2026-10-05T00:00:00+00:00",
        "tool": {"name": "immich-cn", "version": "1.0.0", "revision": "abc123"},
        "sources": [
            {"name": "cities500", "url": "https://example.com/cities500.zip", "sha256": "aaa", "sizeBytes": 1},
            {"name": "admin1CodesASCII", "sha256": "bbb", "sizeBytes": 2},
        ],
        "config": {
            "provider": "offline",
            "patterns": ["{admin_2}"],
            "extraCountries": ["CN"],
            "minPopulation": 100,
            "chineseVariant": "hans",
        },
    }
    manifest.update(overrides)
    return manifest


def test_fingerprint_is_stable() -> None:
    assert data_fingerprint(make_manifest()) == data_fingerprint(make_manifest())


def test_fingerprint_ignores_non_content_fields() -> None:
    first = data_fingerprint(make_manifest())
    second = data_fingerprint(make_manifest(generatedAt="2030-01-01T00:00:00+00:00", stats={"x": 1}))
    assert first == second


def test_fingerprint_ignores_source_order() -> None:
    reordered = make_manifest()
    sources = list(reordered["sources"])  # type: ignore[arg-type]
    reordered["sources"] = list(reversed(sources))
    assert data_fingerprint(make_manifest()) == data_fingerprint(reordered)


def test_fingerprint_ignores_key_order() -> None:
    """同一份配置换个键序不应改变指纹，否则会被误判为「有变化」而重复发布。"""
    reordered = make_manifest()
    config = reordered["config"]
    tool = reordered["tool"]
    assert isinstance(config, dict) and isinstance(tool, dict)
    reordered["config"] = {key: config[key] for key in reversed(list(config))}
    reordered["tool"] = {key: tool[key] for key in reversed(list(tool))}
    assert data_fingerprint(make_manifest()) == data_fingerprint(reordered)


def test_fingerprint_changes_with_source_content() -> None:
    changed = make_manifest()
    changed["sources"] = [{"name": "cities500", "sha256": "changed"}]
    assert data_fingerprint(changed) != data_fingerprint(make_manifest())


def test_fingerprint_changes_with_build_config() -> None:
    changed = make_manifest()
    changed["config"] = {"provider": "amap", "patterns": ["{admin_2}"], "extraCountries": ["CN"]}
    assert data_fingerprint(changed) != data_fingerprint(make_manifest())


def test_fingerprint_changes_with_schema_version() -> None:
    changed = make_manifest(schemaVersion=2)
    assert data_fingerprint(changed) != data_fingerprint(make_manifest())


def test_fingerprint_changes_with_tool_revision() -> None:
    changed = make_manifest(tool={"name": "immich-cn", "version": "1.0.0", "revision": "def456"})
    assert data_fingerprint(changed) != data_fingerprint(make_manifest())


def test_fingerprint_changes_with_tool_version() -> None:
    changed = make_manifest(tool={"name": "immich-cn", "version": "1.0.1", "revision": "abc123"})
    assert data_fingerprint(changed) != data_fingerprint(make_manifest())


def test_fingerprint_from_file(tmp_path: Path) -> None:
    path = tmp_path / "immich-cn-manifest-json-v1.json"
    path.write_text(json.dumps(make_manifest()), encoding="utf-8")
    assert fingerprint_from_file(str(path)) == data_fingerprint(make_manifest())


@pytest.mark.parametrize("sources", [[], [None], [{"name": "cities500"}], "bad"])
def test_fingerprint_rejects_malformed_sources(sources: object) -> None:
    with pytest.raises(ValueError, match=r"manifest\.sources"):
        data_fingerprint(make_manifest(sources=sources))


@pytest.mark.parametrize("field", ["config", "tool"])
def test_fingerprint_rejects_non_mapping_sections(field: str) -> None:
    with pytest.raises(ValueError, match=rf"manifest\.{field}"):
        data_fingerprint(make_manifest(**{field: None}))


@pytest.mark.parametrize("tool", [{}, {"name": "immich-cn"}, {"name": "immich-cn", "version": "1.0.0"}])
def test_fingerprint_rejects_incomplete_tool(tool: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=r"manifest\.tool"):
        data_fingerprint(make_manifest(tool=tool))


@pytest.mark.parametrize("schema_version", [None, 0, -1, "1", 1.5, True])
def test_fingerprint_rejects_invalid_schema_version(schema_version: object) -> None:
    with pytest.raises(ValueError, match=r"manifest\.schemaVersion"):
        data_fingerprint(make_manifest(schemaVersion=schema_version))
