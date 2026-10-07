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
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SEMVER = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
PACKAGE_TAGS = {"latest", "release"}
PACKAGE_NAMES = ("immich-cn", "immich-cn-server")
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
CANONICAL_ASSET = re.compile(
    r"^immich-cn-(?:"
    r"geodata-[a-z0-9-]+-(?:default|full)-v[0-9]+\.zip|"
    r"dataset-sqlite-v[0-9]+\.zip|"
    r"patterns-tsv-v[0-9]+\.gz|"
    r"i18n-json-v[0-9]+\.zip|"
    r"manifest-json-v[0-9]+\.json|"
    r"checksums-sha256-v[0-9]+\.txt"
    r")$"
)
LEGACY_RELEASE_ASSETS = frozenset(
    {
        "SHA256SUMS",
        "dataset.sqlite.zip",
        "geodata.zip",
        "geodata_admin_2.zip",
        "geodata_admin_2_admin_3.zip",
        "geodata_admin_2_admin_3_admin_4.zip",
        "geodata_admin_2_admin_3_admin_4_full.zip",
        "geodata_admin_2_admin_3_full.zip",
        "geodata_admin_2_admin_4.zip",
        "geodata_admin_2_admin_4_full.zip",
        "geodata_admin_2_full.zip",
        "geodata_admin_3.zip",
        "geodata_admin_3_admin_4.zip",
        "geodata_admin_3_admin_4_full.zip",
        "geodata_admin_3_full.zip",
        "geodata_admin_4.zip",
        "geodata_admin_4_full.zip",
        "geodata_full.zip",
        "i18n-iso-countries.zip",
        "manifest.json",
        "patterns.tsv.gz",
    }
)


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
    #: 仅更新监控使用；清理流程只关心 ``status``。默认值保证既有调用点不受影响。
    conclusion: str = ""
    event: str = ""


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
    inventory: Inventory

    @property
    def total(self) -> int:
        return len(self.releases) + len(self.runs) + sum(len(items) for items in self.package_versions.values())


@dataclass(frozen=True, slots=True)
class Inventory:
    """清理前真实读到的对象数量。

    「0 待删除」必须能和「什么都没读到」区分开：2026-10-07 的 dry-run 只打印四行 0，
    无法证明 Packages API 真的返回了版本列表。Inventory 把观察到的总数一并打印，
    并在某个包读到空列表时直接失败（除非显式 --allow-empty-packages）。
    """

    releases: int
    runs: int
    package_versions: dict[str, int]

    def describe(self) -> str:
        packages = "、".join(f"{name}={count}" for name, count in sorted(self.package_versions.items()))
        return f"观察到 Release {self.releases} 个、Actions 运行 {self.runs} 次、GHCR 版本 {packages}"


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
        conclusion=str(payload.get("conclusion") or ""),
        event=str(payload.get("event") or ""),
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
        if run.id == current_run_id or run.head_sha in protected_shas or (not prune_all and run.created_at >= cutoff):
            keep.add(run.id)
    return tuple(run for run in runs if run.status == "completed" and run.id not in keep)


def select_stale_assets(assets: list[tuple[int, str]], keep: set[str]) -> list[tuple[int, str]]:
    """返回不在 keep 清单里的 Release 资产。

    发布路径是 `gh release upload --clobber`：它只增不删，命名规范变更后旧资产会长期残留
    （v4 迁移后 auto-release 上留下 21 个 pre-v4 资产）。这里按名单排序，便于复现与断言。
    """
    return sorted(((asset_id, name) for asset_id, name in assets if name not in keep), key=lambda item: item[1])


def select_legacy_assets(
    assets: list[tuple[int, str]],
    *,
    canonical_available: bool = False,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """返回 ``(可安全删除的旧资产, 缺少规范资产的旧资产)``。

    仓库中已经存在规范 v4 资产时，才删除旧命名资产；否则保留并在输出中标记为
    待人工确认，避免把仍作为唯一分发入口的历史版本清空。
    """
    legacy = [(asset_id, name) for asset_id, name in assets if name in LEGACY_RELEASE_ASSETS]
    if not legacy:
        return [], []
    has_canonical = canonical_available or any(CANONICAL_ASSET.fullmatch(name) for _, name in assets)
    ordered = sorted(legacy, key=lambda item: item[1])
    return (ordered, []) if has_canonical else ([], ordered)


def select_package_versions(
    versions: list[PackageVersionRecord],
    *,
    retention: int,
    prune_all: bool,
) -> tuple[PackageVersionRecord, ...]:
    """保留语义版本、稳定标签、digest-like tag、最新版本与 untagged 子 manifest，返回应删除项。"""
    keep: set[int] = set()
    candidates: list[PackageVersionRecord] = []
    for version in versions:
        protected = any(
            SEMVER.match(tag) or tag in PACKAGE_TAGS or tag.startswith(("sha256-", "sha256:")) for tag in version.tags
        )
        if protected or not version.tags:
            keep.add(version.id)
        else:
            candidates.append(version)
    ordered = sorted(candidates, key=lambda version: version.created_at, reverse=True)
    keep_count = 1 if prune_all else retention
    keep.update(version.id for version in ordered[:keep_count])
    # untagged 版本通常是多架构索引的子 manifest 或 attestation；直接删除会破坏父索引。
    return tuple(version for version in versions if version.id not in keep and version.tags)


class GitHubClient:
    """自动化脚本共用的最小 GitHub REST API（清理与更新监控）。"""

    def __init__(self, repository: str, token: str) -> None:
        if not token:
            raise CleanupError("缺少 GITHUB_TOKEN")
        self.repository = repository
        self.owner = repository.split("/", 1)[0]
        self.token = token

    def _request(self, method: str, path: str, *, allow_not_found: bool = False) -> Any:
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
        for attempt in range(MAX_ATTEMPTS):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                    body = response.read()
                break
            except urllib.error.HTTPError as error:
                try:
                    if allow_not_found and error.code == 404:
                        return None
                    detail = error.read().decode("utf-8", errors="replace")[:400]
                    if error.code in RETRY_STATUS and attempt + 1 < MAX_ATTEMPTS:
                        time.sleep(min(2**attempt, 30))
                        continue
                    raise CleanupError(f"{method} {path} -> HTTP {error.code}: {detail}") from error
                finally:
                    error.close()
            except OSError as error:
                if attempt + 1 < MAX_ATTEMPTS:
                    time.sleep(min(2**attempt, 30))
                    continue
                raise CleanupError(f"{method} {path} 失败：{error}") from error
        else:  # pragma: no cover - 循环要么 break 要么抛错
            raise CleanupError(f"{method} {path} 重试耗尽")
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

    def list_workflow_runs(self, workflow_file: str, *, limit: int = 30) -> list[RunRecord]:
        """按工作流文件读取最近若干次运行（单次请求，不翻页）。

        更新监控只关心最近几次运行，整仓 ``list_runs()`` 会翻遍所有历史，
        既慢又会因为保留策略删过记录而给出误导性的结果。
        """
        if not 1 <= limit <= 100:
            raise CleanupError(f"limit 必须在 1..100 之间，收到 {limit}")
        encoded = urllib.parse.quote(workflow_file, safe="")
        payload = self._request(
            "GET",
            f"/repos/{self.repository}/actions/workflows/{encoded}/runs?per_page={limit}",
        )
        raw = payload.get("workflow_runs") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            raise CleanupError(f"无法解析 {workflow_file} 的运行列表")
        return [_run_record(item) for item in raw if isinstance(item, dict)]

    def list_package_versions(self, package: str) -> list[PackageVersionRecord]:
        encoded = urllib.parse.quote(package, safe="")
        return [
            _package_record(item) for item in self._list(f"/users/{self.owner}/packages/container/{encoded}/versions")
        ]

    def commit_sha_for_tag(self, tag: str) -> str:
        encoded = urllib.parse.quote(tag, safe="")
        payload = self._request("GET", f"/repos/{self.repository}/commits/{encoded}")
        return str(payload.get("sha", "")) if isinstance(payload, dict) else ""

    def release_assets(self, tag: str) -> list[tuple[int, str]]:
        """返回 `<asset_id, name>` 列表；用于按当前 dist 清单回收滚动 Release 的旧资产。"""
        encoded = urllib.parse.quote(tag, safe="")
        payload = self._request("GET", f"/repos/{self.repository}/releases/tags/{encoded}")
        if not isinstance(payload, dict) or "id" not in payload:
            raise CleanupError(f"无法解析 Release {tag} 的元数据")
        assets = self._list(f"/repos/{self.repository}/releases/{payload['id']}/assets")
        return sorted(
            (int(item["id"]), str(item["name"]))
            for item in assets
            if isinstance(item.get("id"), int) and item.get("name")
        )

    def delete_release_asset(self, asset_id: int) -> None:
        self._request(
            "DELETE",
            f"/repos/{self.repository}/releases/assets/{asset_id}",
            allow_not_found=True,
        )

    def delete_release(self, release: ReleaseRecord) -> None:
        self._request("DELETE", f"/repos/{self.repository}/releases/{release.id}", allow_not_found=True)
        encoded = urllib.parse.quote(release.tag_name, safe="")
        self._request(
            "DELETE",
            f"/repos/{self.repository}/git/refs/tags/{encoded}",
            allow_not_found=True,
        )

    def delete_run(self, run: RunRecord) -> None:
        self._request(
            "DELETE",
            f"/repos/{self.repository}/actions/runs/{run.id}",
            allow_not_found=True,
        )

    def delete_package_version(self, package: str, version: PackageVersionRecord) -> None:
        encoded = urllib.parse.quote(package, safe="")
        self._request(
            "DELETE",
            f"/users/{self.owner}/packages/container/{encoded}/versions/{version.id}",
            allow_not_found=True,
        )


def build_plan(
    client: GitHubClient,
    settings: CleanupSettings,
    *,
    allow_empty_packages: bool = False,
) -> CleanupPlan:
    settings.validate()
    releases = client.list_releases()
    protected_shas = {
        client.commit_sha_for_tag(release.tag_name) for release in releases if SEMVER.match(release.tag_name)
    }
    protected_shas.discard("")
    runs = client.list_runs()
    cutoff = datetime.now(UTC) - timedelta(days=settings.run_retention_days)
    current_run_id = int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID", "").isdigit() else None
    observed: dict[str, list[PackageVersionRecord]] = {}
    for package in PACKAGE_NAMES:
        versions = client.list_package_versions(package)
        if not versions and not allow_empty_packages:
            raise CleanupError(
                f"GHCR 包 {package} 返回 0 个版本：无法区分「确实没有版本」与「token 缺少 "
                "read:packages / API 结构变化导致读到空列表」。拒绝在没有证据的情况下报告清理成功；"
                "确认该包尚未创建时显式加 --allow-empty-packages"
            )
        observed[package] = versions
    package_versions = {
        package: select_package_versions(
            versions,
            retention=settings.package_retention,
            prune_all=settings.prune_all,
        )
        for package, versions in observed.items()
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
        inventory=Inventory(
            releases=len(releases),
            runs=len(runs),
            package_versions={package: len(versions) for package, versions in observed.items()},
        ),
    )


def print_plan(plan: CleanupPlan, *, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] {plan.inventory.describe()}")
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
    """执行清理；单项失败不阻断其他删除，最后统一失败。"""
    failures: list[str] = []

    def attempt(label: str, action: Callable[[], None]) -> None:
        try:
            action()
        except CleanupError as error:
            failures.append(f"{label}: {error}")

    for run in plan.runs:
        attempt(f"run {run.id}", lambda run=run: client.delete_run(run))
    for release in plan.releases:
        attempt(f"release {release.tag_name}", lambda release=release: client.delete_release(release))
    for package, versions in plan.package_versions.items():
        for version in versions:
            attempt(
                f"package {package} version {version.id}",
                lambda package=package, version=version: client.delete_package_version(package, version),
            )
    if failures:
        detail = "；".join(failures[:5])
        if len(failures) > 5:
            detail += f"；另有 {len(failures) - 5} 项"
        raise CleanupError(f"清理部分失败：{len(failures)} 项：{detail}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="执行删除；缺省只做 dry-run")
    parser.add_argument("--prune-all", action="store_true", help="稳定前激进清理，只保留最新数据快照和受保护镜像")
    parser.add_argument("--release-retention", type=int, default=14)
    parser.add_argument("--run-retention-days", type=int, default=30)
    parser.add_argument("--run-keep-per-workflow", type=int, default=20)
    parser.add_argument("--package-retention", type=int, default=20)
    parser.add_argument(
        "--allow-empty-packages",
        action="store_true",
        help="允许某个 GHCR 包返回 0 个版本（仅在包确实尚未创建时使用）",
    )
    parser.add_argument(
        "--prune-release-assets",
        metavar="TAG",
        help="按 --dist-dir 的文件清单回收该 Release 中多余的资产（缺省 dry-run）",
    )
    parser.add_argument(
        "--verify-release-assets",
        metavar="TAG",
        help="验证 Release 资产与 --dist-dir 文件清单完全一致；不一致时返回 1",
    )
    parser.add_argument(
        "--prune-legacy-assets",
        action="store_true",
        help="仓库中已有规范 v4 替代品时删除旧命名发布资产（缺省 dry-run）",
    )
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"), help="--prune-release-assets 使用的本地清单目录")
    return parser


def _release_manifest(dist_dir: Path) -> set[str]:
    if not dist_dir.is_dir():
        raise CleanupError(f"{dist_dir} 不是目录，无法作为清单来源")
    files = {path.name for path in dist_dir.iterdir() if path.is_file()}
    if not files:
        raise CleanupError(f"{dist_dir} 中没有文件，拒绝使用空清单")
    return files


def _prune_release_assets(client: GitHubClient, args: argparse.Namespace) -> int:
    """按本地 dist 清单回收 Release 中不再发布的资产。"""
    keep = _release_manifest(args.dist_dir)
    assets = client.release_assets(args.prune_release_assets)
    if not (keep & {name for _, name in assets}):
        raise CleanupError(
            f"{args.dist_dir} 与 Release {args.prune_release_assets} 的资产没有任何交集，拒绝删除（疑似清单来源错误）"
        )
    stale = select_stale_assets(assets, keep)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] Release {args.prune_release_assets}：现有 {len(assets)} 个资产，待删除 {len(stale)} 个")
    failures: list[str] = []
    for asset_id, name in stale:
        print(f"  - {name}")
        if args.apply:
            try:
                client.delete_release_asset(asset_id)
            except CleanupError as error:
                failures.append(f"{name}: {error}")
    if failures:
        detail = "；".join(failures[:5])
        if len(failures) > 5:
            detail += f"；另有 {len(failures) - 5} 项"
        raise CleanupError(f"Release {args.prune_release_assets} 资产清理部分失败：{len(failures)} 项：{detail}")
    return 0


def _verify_release_assets(client: GitHubClient, args: argparse.Namespace) -> int:
    """验证 Release 资产集合与本地 dist 完全一致。"""
    expected = _release_manifest(args.dist_dir)
    assets = client.release_assets(args.verify_release_assets)
    actual = {name for _, name in assets}
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if not missing and not extra:
        print(f"[OK] Release {args.verify_release_assets}：{len(actual)} 个资产与 dist 完全一致")
        return 0
    print(
        f"[!!] Release {args.verify_release_assets} 与 dist 不一致：缺少 {len(missing)} 个，多出 {len(extra)} 个",
        file=sys.stderr,
    )
    for name in missing:
        print(f"  missing: {name}", file=sys.stderr)
    for name in extra:
        print(f"  extra: {name}", file=sys.stderr)
    return 1


def _prune_legacy_assets(client: GitHubClient, args: argparse.Namespace) -> int:
    """删除已有规范替代品的旧命名发布资产；缺少规范资产的发布只报告不删除。"""
    releases = client.list_releases()
    observed = {release.tag_name: client.release_assets(release.tag_name) for release in releases}
    canonical_available = any(CANONICAL_ASSET.fullmatch(name) for assets in observed.values() for _, name in assets)
    mode = "APPLY" if args.apply else "DRY-RUN"
    deletable_total = 0
    manual_total = 0
    failures: list[str] = []
    for release in releases:
        assets = observed[release.tag_name]
        deletable, manual = select_legacy_assets(assets, canonical_available=canonical_available)
        if not deletable and not manual:
            continue
        if deletable:
            print(f"[{mode}] Release {release.tag_name}：待删除旧资产 {len(deletable)} 个")
        if manual:
            manual_total += len(manual)
            print(f"[{mode}] Release {release.tag_name}：缺少规范替代品，保留旧资产 {len(manual)} 个")
        for asset_id, name in deletable:
            print(f"  - {name}")
            if args.apply:
                try:
                    client.delete_release_asset(asset_id)
                except CleanupError as error:
                    failures.append(f"{release.tag_name}/{name}: {error}")
        for _, name in manual:
            print(f"  ! {name}（无规范替代品，跳过）")
        deletable_total += len(deletable)
    print(f"[{mode}] 旧命名资产：可删除 {deletable_total} 个，需人工确认 {manual_total} 个")
    if failures:
        detail = "；".join(failures[:5])
        if len(failures) > 5:
            detail += f"；另有 {len(failures) - 5} 项"
        raise CleanupError(f"旧命名资产清理部分失败：{len(failures)} 项：{detail}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    modes = (
        bool(args.prune_release_assets),
        bool(args.verify_release_assets),
        args.prune_legacy_assets,
    )
    if sum(modes) > 1:
        print("::error::Release 资产清理模式不能同时使用", file=sys.stderr)
        return 2
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
        if args.prune_release_assets:
            return _prune_release_assets(client, args)
        if args.verify_release_assets:
            return _verify_release_assets(client, args)
        if args.prune_legacy_assets:
            return _prune_legacy_assets(client, args)
        plan = build_plan(client, settings, allow_empty_packages=args.allow_empty_packages)
        print_plan(plan, apply=args.apply)
        if args.apply:
            apply_plan(client, plan)
        return 0
    except CleanupError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
