from __future__ import annotations

import json
from pathlib import Path

import pytest

from immich_cn.artifacts import (
    artifact_id,
    canonical_filename,
    profile_id,
    resolve_artifact,
    validate_artifact_id,
    validate_canonical_filename,
)
from immich_cn.cli import main
from immich_cn.errors import ConfigError


def manifest() -> dict[str, object]:
    return {
        "artifactSpecVersion": 2,
        "artifacts": [
            {
                "id": "geodata.immich.admin2.default.v1",
                "file": "geodata.zip",
                "canonicalFile": "immich-cn-geodata-immich-admin2-default-v1.zip",
                "profile": "admin2",
                "scope": "default",
                "sha256": "a" * 64,
            },
            {
                "id": "geodata.immich.admin2-admin3.full.v1",
                "file": "geodata_admin_2_admin_3_full.zip",
                "canonicalFile": "immich-cn-geodata-immich-admin2-admin3-full-v1.zip",
                "profile": "admin2-admin3",
                "scope": "full",
                "sha256": "b" * 64,
            },
        ],
        "aliases": {"geodata.zip": "geodata.immich.admin2.default.v1"},
        "legacyAliases": {
            "geodata_admin_2.zip": "geodata.immich.admin2.default.v1",
            "geodata_admin_2_admin_3_full.zip": "geodata.immich.admin2-admin3.full.v1",
        },
    }


def test_artifact_ids_are_stable_and_profile_safe() -> None:
    assert profile_id("{admin_2}") == "admin2"
    assert profile_id("{admin_2} {admin_3}") == "admin2-admin3"
    assert artifact_id("{admin_2} {admin_3}", False) == "geodata.immich.admin2-admin3.default.v1"
    assert canonical_filename("{admin_2} {admin_3}", True) == "immich-cn-geodata-immich-admin2-admin3-full-v1.zip"
    assert validate_artifact_id("geodata.immich.admin2-admin3.default.v1")
    assert not validate_artifact_id("geodata.immich.admin_2.default.v1")
    assert validate_canonical_filename("immich-cn-geodata-immich-admin2-default-v1.zip")
    assert not validate_canonical_filename("geodata_admin_2.zip")


def test_resolve_artifact_by_id_alias_and_profile() -> None:
    payload = manifest()
    assert resolve_artifact(payload, artifact_id="geodata.immich.admin2.default.v1")["file"] == "geodata.zip"
    assert resolve_artifact(payload, alias="geodata.zip")["profile"] == "admin2"
    assert resolve_artifact(payload, alias="geodata_admin_2.zip")["profile"] == "admin2"
    assert resolve_artifact(payload, profile="admin2-admin3", scope="full")["file"].endswith("_full.zip")


def test_resolve_artifact_rejects_missing_or_ambiguous_selectors() -> None:
    with pytest.raises(ConfigError, match="必须提供"):
        resolve_artifact(manifest())
    with pytest.raises(ConfigError, match="没有 alias"):
        resolve_artifact(manifest(), alias="missing.zip")
    with pytest.raises(ConfigError, match="没有匹配"):
        resolve_artifact(manifest(), profile="admin4", scope="default")


def test_cli_artifact_resolve(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest(), ensure_ascii=False), encoding="utf-8")

    assert main(["artifact", "resolve", "--manifest", str(path), "--alias", "geodata.zip"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["id"] == "geodata.immich.admin2.default.v1"
    assert output["file"] == "geodata.zip"
