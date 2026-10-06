from __future__ import annotations

from immich_cn.artifacts import (
    artifact_id,
    canonical_filename,
    profile_id,
    validate_artifact_id,
    validate_canonical_filename,
)


def test_artifact_ids_are_stable_and_profile_safe() -> None:
    assert profile_id("{admin_2}") == "admin2"
    assert profile_id("{admin_2} {admin_3}") == "admin2-admin3"
    assert artifact_id("{admin_2} {admin_3}", False) == "geodata.immich.admin2-admin3.default.v1"
    assert canonical_filename("{admin_2} {admin_3}", True) == "immich-cn-geodata-immich-admin2-admin3-full-v1.zip"
    assert validate_artifact_id("geodata.immich.admin2-admin3.default.v1")
    assert not validate_artifact_id("geodata.immich.admin_2.default.v1")
    assert validate_canonical_filename("immich-cn-geodata-immich-admin2-default-v1.zip")
    assert not validate_canonical_filename("geodata_admin_2.zip")
