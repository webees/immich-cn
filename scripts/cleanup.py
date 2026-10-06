"""按保留策略清理 Release、Actions 运行记录与 GHCR 包版本。

默认只做 dry-run；工作流在定时任务中显式传入 ``--apply``。
所有删除规则都先经过纯函数选择，便于测试和审计。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

SEMVER = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
PACKAGE_TAGS = {"latest", "release"}
PACKAGE_NAMES = ("immich-cn", "immich-cn-server")


class CleanupError(RuntimeError):
    """清理 API 调用或配置错误。"""


@dataclass(frozen=True, slots=True)
class ReleaseRecord:
    id: int
    tag_name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: int
    name: str
    status: str
    created_at: datetime
    head_sha: str


@dataclass(frozen=True, slots=True)
class PackageVersionRecord:
    id: int
    created_at: datetime
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CleanupSettings:
    release_retention: int
    run_retention_days: int
    run_keep_per_workflow: int
    package_retention: int
    prune_all: bool

    def validate(self) -> None:
        for name, value in (
            ("release_retention", self.release_retention),
            ("run_retention_days", self.run_retention_days),
            ("run_keep_per_workflow", self.run_keep_per_workflow),
            ("package_retention", self.package_retention),
        ):
            if value < 1:
                raise CleanupError(f"{name} 必须大于 0")


@dataclass(frozen=True, slots=True)
class CleanupPlan:
    releases: tuple[ReleaseRecord, ...]
    runs: tuple[RunRecord, ...]
    package_versions: dict[str, tuple[PackageVersionRecord, ...]]


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CleanupError(f"无法解析 GitHub 时间：{value!r}") from error
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _release_record(payload: dict[str, Any]) -> ReleaseRecord:
    return ReleaseRecord(
        id=int(payload["id"]),
        tag_name=str(payload["tag_name"]),
        created_at=_parse_time(str(payload["created_at"])),
    )


def _run_record(payload: dict[str, Any]) -> RunRecord:
    return RunRecord(
        id=int(payload["id"]),
        name=str(payload.get("name") or "unknown"),
        status=str(payload.get("status") or "unknown"),
        created_at=_parse_time(str(payload["created_at"])),
        head_sha=str(payload.get("head_sha") or ""),
    )


def _package_record(payload: dict[str, Any]) -> PackageVersionRecord:
    metadata = payload.get("metadata")
    tags: tuple[str, ...] = ()
    if isinstance(metadata, dict):
        container = metadata.get("container")
        if isinstance(container, dict) and isinstance(container.get("tags"), list):
            tags = tuple(str(tag) for tag in container["tags"])
    return PackageVersionRecord(
        id=int(payload["id"]),
        created_at=_parse_time(str(payload["created_at"])),
        tags=tags,
    )


def select_releases(
    releases: list[ReleaseRecord],
    *,
    retention: int,
    prune_all: bool,
) -> tuple[ReleaseRecord, ...]:
    """保留语义版本、auto-release 与最新数据快照，返回应删除项。"""
    keep: set[int] = set()
    for release in releases:
        if release.tag_name == "auto-release" or SEMVER.match(release.tag_name):
            keep.add(release.id)
    data_snapshots = sorted(
        (release for release in releases if release.tag_name.startswith("data-")),
        key=lambda release: release.created_at,
        reverse=True,
    )
    keep_count = 1 if prune_all else retention
    keep.update(release.id for release in data_snapshots[:keep_count])
    return tuple(release for release in releases if release.id not in keep)


def select_runs(
    runs: list[RunRecord],
    *,
    cutoff: datetime,
    keep_per_workflow: int,
    protected_shas: set[str],
    current_run_id: int | None,
    prune_all: bool,
) -> tuple[RunRecord, ...]:
    """保留近期运行、每个工作流最新记录与受保护提交，返回应删除项。"""
    keep: set[int] = set()
    grouped: dict[str, list[RunRecord]] = {}
    for run in sorted(runs, key=lambda item: item.created_at, reverse=True):
        grouped.setdefault(run.name, []).append(run)
    keep_count = 1 if prune_all else keep_per_workflow
    for grouped_runs in grouped.values():
        keep.update(run.id for run in grouped_runs[:keep_count])
    for run in runs:
        if run.id == current_run_id or run.head_sha in protected_shas or run.created_at >= cutoff:
            keep.add(run.id)
    return tuple(run for run in runs if run.status == "completed" and run.id not in keep)


def select_package_versions(
    versions: list[PackageVersionRecord],
    *,
    retention: int,
    prune_all: bool,
) -> tuple[PackageVersionRecord, ...]:
    """保留语义版本、稳定标签、最新版本与全部 untagged 子 manifest，返回应删除项。"""
    keep: set[int] = set()
    for version in versions:
        if any(SEMVER.match(tag) or tag in PACKAGE_TAGS for tag in version.tags):
            keep.add(version.id)
    ordered = sorted(versions, key=lambda version: version.created_at, reverse=True)
    keep_count = 1 if prune_all else retention
    keep.update(version.id for version in ordered[:keep_count])
    # untagged 版本通常是多架构索引的子 manifest 或 attestation；直接删除会破坏父索引。
    return tuple(version for version in versions if version.id not in keep and version.tags)


class GitHubClient:
    """只实现清理流程需要的最小 GitHub REST API。"""

    def __init__(self, repository: str, token: str) -> None:
        if not token:
            raise CleanupError("缺少 GITHUB_TOKEN")
        self.repository = repository
        self.owner = repository.split("/", 1)[0]
        self.token = token

    def _request(self, method: str, path: str) -> Any:
        request = urllib.request.Request(
            f"https://api.github.com{path}",
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "immich-cn-cleanup",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if not request.full_url.startswith("https://api.github.com/"):
            raise CleanupError(f"拒绝非 GitHub API URL：{request.full_url}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:400]
            raise CleanupError(f"{method} {path} -> HTTP {error.code}: {detail}") from error
        except OSError as error:
            raise CleanupError(f"{method} {path} 失败：{error}") from error
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise CleanupError(f"{method} {path} 返回非 JSON") from error

    def _list(self, path: str, *, key: str | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, 101):
            separator = "&" if "?" in path else "?"
            payload = self._request("GET", f"{path}{separator}per_page=100&page={page}")
            if isinstance(payload, list):
                current = payload
            elif isinstance(payload, dict) and key is not None:
                raw = payload.get(key)
                current = raw if isinstance(raw, list) else []
            else:
                raise CleanupError(f"GET {path} 返回结构无法识别")
            items.extend(item for item in current if isinstance(item, dict))
            if len(current) < 100:
                break
        return items

    def list_releases(self) -> list[ReleaseRecord]:
        return [_release_record(item) for item in self._list(f"/repos/{self.repository}/releases")]

    def list_runs(self) -> list[RunRecord]:
        return [_run_record(item) for item in self._list(f"/repos/{self.repository}/actions/runs", key="workflow_runs")]

    def list_package_versions(self, package: str) -> list[PackageVersionRecord]:
        encoded = urllib.parse.quote(package, safe="")
        return [
            _package_record(item) for item in self._list(f"/users/{self.owner}/packages/container/{encoded}/versions")
        ]

    def commit_sha_for_tag(self, tag: str) -> str:
        encoded = urllib.parse.quote(tag, safe="")
        payload = self._request("GET", f"/repos/{self.repository}/commits/{encoded}")
        return str(payload.get("sha", "")) if isinstance(payload, dict) else ""

    def delete_release(self, release: ReleaseRecord) -> None:
        self._request("DELETE", f"/repos/{self.repository}/releases/{release.id}")
        encoded = urllib.parse.quote(release.tag_name, safe="")
        try:
            self._request("DELETE", f"/repos/{self.repository}/git/refs/tags/{encoded}")
        except CleanupError as error:
            if "HTTP 404" not in str(error):
                raise

    def delete_run(self, run: RunRecord) -> None:
        self._request("DELETE", f"/repos/{self.repository}/actions/runs/{run.id}")

    def delete_package_version(self, package: str, version: PackageVersionRecord) -> None:
        encoded = urllib.parse.quote(package, safe="")
        self._request(
            "DELETE",
            f"/users/{self.owner}/packages/container/{encoded}/versions/{version.id}",
        )


def build_plan(client: GitHubClient, settings: CleanupSettings) -> CleanupPlan:
    settings.validate()
    releases = client.list_releases()
    protected_shas = {
        client.commit_sha_for_tag(release.tag_name) for release in releases if SEMVER.match(release.tag_name)
    }
    protected_shas.discard("")
    runs = client.list_runs()
    cutoff = datetime.now(UTC) - timedelta(days=settings.run_retention_days)
    current_run_id = int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID", "").isdigit() else None
    package_versions = {
        package: select_package_versions(
            client.list_package_versions(package),
            retention=settings.package_retention,
            prune_all=settings.prune_all,
        )
        for package in PACKAGE_NAMES
    }
    return CleanupPlan(
        releases=select_releases(
            releases,
            retention=settings.release_retention,
            prune_all=settings.prune_all,
        ),
        runs=select_runs(
            runs,
            cutoff=cutoff,
            keep_per_workflow=settings.run_keep_per_workflow,
            protected_shas=protected_shas,
            current_run_id=current_run_id,
            prune_all=settings.prune_all,
        ),
        package_versions=package_versions,
    )


def print_plan(plan: CleanupPlan, *, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] 待删除 Release：{len(plan.releases)}")
    for release in plan.releases:
        print(f"  release {release.tag_name}")
    print(f"[{mode}] 待删除 Actions 运行：{len(plan.runs)}")
    for run in plan.runs:
        print(f"  run {run.id} {run.name}")
    for package, versions in plan.package_versions.items():
        print(f"[{mode}] 待删除 GHCR 版本 {package}：{len(versions)}")
        for version in versions:
            print(f"  version {version.id} tags={','.join(version.tags) or '<untagged>'}")


def apply_plan(client: GitHubClient, plan: CleanupPlan) -> None:
    for run in plan.runs:
        client.delete_run(run)
    for release in plan.releases:
        client.delete_release(release)
    for package, versions in plan.package_versions.items():
        for version in versions:
            client.delete_package_version(package, version)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="执行删除；缺省只做 dry-run")
    parser.add_argument("--prune-all", action="store_true", help="稳定前激进清理，只保留最新数据快照和受保护镜像")
    parser.add_argument("--release-retention", type=int, default=14)
    parser.add_argument("--run-retention-days", type=int, default=30)
    parser.add_argument("--run-keep-per-workflow", type=int, default=20)
    parser.add_argument("--package-retention", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = CleanupSettings(
        release_retention=args.release_retention,
        run_retention_days=args.run_retention_days,
        run_keep_per_workflow=args.run_keep_per_workflow,
        package_retention=args.package_retention,
        prune_all=args.prune_all,
    )
    try:
        client = GitHubClient(
            repository=os.environ.get("GITHUB_REPOSITORY", "webees/immich-cn"),
            token=os.environ.get("PACKAGE_ADMIN_TOKEN") or os.environ.get("GITHUB_TOKEN", ""),
        )
        plan = build_plan(client, settings)
        print_plan(plan, apply=args.apply)
        if args.apply:
            apply_plan(client, plan)
        return 0
    except CleanupError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
