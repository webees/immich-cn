from __future__ import annotations

import json
from pathlib import Path

from immich_cn.fingerprint import data_fingerprint, fingerprint_from_file


def make_manifest(**overrides: object) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "generatedAt": "2026-10-05T00:00:00+00:00",
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


def test_fingerprint_changes_with_source_content() -> None:
    changed = make_manifest()
    changed["sources"] = [{"name": "cities500", "sha256": "changed"}]
    assert data_fingerprint(changed) != data_fingerprint(make_manifest())


def test_fingerprint_changes_with_build_config() -> None:
    changed = make_manifest()
    changed["config"] = {"provider": "amap", "patterns": ["{admin_2}"], "extraCountries": ["CN"]}
    assert data_fingerprint(changed) != data_fingerprint(make_manifest())


def test_fingerprint_from_file(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(make_manifest()), encoding="utf-8")
    assert fingerprint_from_file(str(path)) == data_fingerprint(make_manifest())
