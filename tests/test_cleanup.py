from __future__ import annotations

import io
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts.cleanup import (
    CleanupError,
    CleanupSettings,
    GitHubClient,
    PackageVersionRecord,
    ReleaseRecord,
    RunRecord,
    _prune_release_assets,
    select_package_versions,
    select_releases,
    select_runs,
    select_stale_assets,
)

#: v4 迁移前发布、因而残留在 auto-release 上的旧资产名（2026-10-07 实测 21 个）。
PRE_V4_ASSETS = (
    "dataset.sqlite.zip",
    "geodata.zip",
    "geodata_admin_2.zip",
    "geodata_admin_3.zip",
    "geodata_admin_4.zip",
    "geodata_full.zip",
    "i18n-iso-countries.zip",
    "manifest.json",
    "patterns.tsv.gz",
    "SHA256SUMS",
)


class FakeResponse:
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return b"{}"


def at(days_ago: int) -> datetime:
    return datetime(2026, 10, 7, tzinfo=UTC) - timedelta(days=days_ago)


def test_cleanup_settings_rejects_non_positive_values() -> None:
    with pytest.raises(CleanupError, match="release_retention"):
        CleanupSettings(0, 30, 20, 20, False).validate()
    with pytest.raises(CleanupError, match="package_retention"):
        CleanupSettings(14, 30, 20, 0, False).validate()


def test_release_cleanup_preserves_semver_auto_and_latest_snapshots() -> None:
    releases = [
        ReleaseRecord(1, "v1.0.4", at(1)),
        ReleaseRecord(2, "auto-release", at(2)),
        ReleaseRecord(3, "data-2026-10-07", at(1)),
        ReleaseRecord(4, "data-2026-10-06", at(2)),
        ReleaseRecord(5, "data-2026-10-05", at(3)),
    ]

    selected = select_releases(releases, retention=2, prune_all=False)

    assert [release.tag_name for release in selected] == ["data-2026-10-05"]


def test_release_cleanup_prune_all_keeps_only_newest_snapshot() -> None:
    releases = [
        ReleaseRecord(1, "v1.0.4", at(1)),
        ReleaseRecord(2, "auto-release", at(2)),
        ReleaseRecord(3, "data-2026-10-07", at(1)),
        ReleaseRecord(4, "data-2026-10-06", at(2)),
    ]

    selected = select_releases(releases, retention=14, prune_all=True)

    assert [release.tag_name for release in selected] == ["data-2026-10-06"]


def test_run_cleanup_preserves_cutoff_latest_per_workflow_protected_and_current() -> None:
    runs = [
        RunRecord(1, "CI", "completed", at(0), "sha-current"),
        RunRecord(2, "CI", "completed", at(1), "sha-old"),
        RunRecord(3, "CI", "completed", at(20), "sha-protected"),
        RunRecord(4, "CI", "completed", at(40), "sha-delete"),
        RunRecord(5, "Release", "completed", at(50), "sha-delete-2"),
        RunRecord(6, "CI", "in_progress", at(60), "sha-active"),
        RunRecord(7, "Release", "completed", at(0), "sha-release-latest"),
    ]

    selected = select_runs(
        runs,
        cutoff=at(7),
        keep_per_workflow=1,
        protected_shas={"sha-protected"},
        current_run_id=1,
        prune_all=False,
    )

    assert {run.id for run in selected} == {4, 5}


def test_run_cleanup_prune_all_keeps_one_per_workflow() -> None:
    runs = [
        RunRecord(1, "CI", "completed", at(0), "a"),
        RunRecord(2, "CI", "completed", at(10), "b"),
        RunRecord(3, "Release", "completed", at(11), "c"),
        RunRecord(4, "Release", "completed", at(12), "d"),
    ]

    selected = select_runs(
        runs,
        cutoff=at(0),
        keep_per_workflow=20,
        protected_shas=set(),
        current_run_id=None,
        prune_all=True,
    )

    assert {run.id for run in selected} == {2, 4}


def test_package_cleanup_preserves_semver_stable_and_recent_versions() -> None:
    versions = [
        PackageVersionRecord(1, at(1), ("v1.0.4",)),
        PackageVersionRecord(2, at(2), ("latest",)),
        PackageVersionRecord(3, at(3), ("release",)),
        PackageVersionRecord(4, at(4), ("2026-10-07",)),
        PackageVersionRecord(5, at(5), ("2026-10-06",)),
        PackageVersionRecord(6, at(6), ("2026-10-05",)),
    ]

    selected = select_package_versions(versions, retention=2, prune_all=False)

    assert [version.id for version in selected] == [4, 5, 6]


def test_package_cleanup_prune_all_keeps_protected_and_newest_version() -> None:
    versions = [
        PackageVersionRecord(1, at(1), ("v1.0.4",)),
        PackageVersionRecord(2, at(2), ("latest",)),
        PackageVersionRecord(3, at(3), ("2026-10-07",)),
        PackageVersionRecord(4, at(4), ("2026-10-06",)),
    ]

    selected = select_package_versions(versions, retention=20, prune_all=True)

    assert [version.id for version in selected] == [3, 4]


def test_package_cleanup_never_deletes_untagged_child_manifests() -> None:
    versions = [
        PackageVersionRecord(1, at(1), ("v1.0.4",)),
        PackageVersionRecord(2, at(2), ("latest",)),
        PackageVersionRecord(3, at(3), ("2026-10-07",)),
        PackageVersionRecord(4, at(4), ()),
        PackageVersionRecord(5, at(5), ()),
    ]

    selected = select_package_versions(versions, retention=1, prune_all=True)

    assert [version.id for version in selected] == [3]


def test_github_client_retries_transient_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        attempts.append(1)
        if len(attempts) < 3:
            raise urllib.error.HTTPError(request.full_url, 500, "transient", {}, io.BytesIO(b""))
        return FakeResponse()

    monkeypatch.setattr("scripts.cleanup.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("scripts.cleanup.time.sleep", lambda _seconds: None)

    client = GitHubClient("webees/immich-cn", "token")
    assert client._request("GET", "/x") == {}
    assert len(attempts) == 3


def test_github_client_allows_not_found_for_idempotent_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        raise urllib.error.HTTPError(request.full_url, 404, "gone", {}, io.BytesIO(b""))

    monkeypatch.setattr("scripts.cleanup.urllib.request.urlopen", fake_urlopen)
    client = GitHubClient("webees/immich-cn", "token")
    assert client._request("DELETE", "/x", allow_not_found=True) is None


def test_select_stale_assets_keeps_current_dist_and_drops_pre_v4_names() -> None:
    """按 dist 清单回收：只保留本次构建的 canonical 资产。"""
    keep = {"immich-cn-geodata-admin2-default-v1.zip", "immich-cn-manifest-json-v1.json"}
    assets = [(index, name) for index, name in enumerate([*sorted(keep), *PRE_V4_ASSETS], start=1)]

    stale = select_stale_assets(assets, keep)

    assert [name for _, name in stale] == sorted(PRE_V4_ASSETS)
    assert not (keep & {name for _, name in stale})


def test_prune_release_assets_refuses_empty_dist(tmp_path: Path) -> None:
    """空清单无法判断该删什么，必须拒绝，避免误删整个 Release。"""

    class _Client:
        def release_assets(self, tag: str) -> list[tuple[int, str]]:
            raise AssertionError("空清单时不应访问 API")

    args = SimpleNamespace(dist_dir=tmp_path, prune_release_assets="auto-release", apply=True)
    with pytest.raises(CleanupError, match="拒绝按空清单"):
        _prune_release_assets(_Client(), args)


def test_prune_release_assets_refuses_disjoint_manifest(tmp_path: Path) -> None:
    """清单与 Release 资产无交集时拒绝删除（疑似命名方案不一致或清单来源错误）。"""
    (tmp_path / "something-else.zip").write_bytes(b"x")

    class _Client:
        def release_assets(self, tag: str) -> list[tuple[int, str]]:
            return [(1, "immich-cn-geodata-admin2-default-v1.zip")]

    args = SimpleNamespace(dist_dir=tmp_path, prune_release_assets="auto-release", apply=True)
    with pytest.raises(CleanupError, match="没有任何交集"):
        _prune_release_assets(_Client(), args)
