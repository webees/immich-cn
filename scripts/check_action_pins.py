"""校验 workflow 里的 Action 固定到真实存在、且与版本注释一致的 commit SHA。

`check_workflows.py` 只做离线格式校验（`uses:` 必须带 40 位十六进制）。它发现不了
「SHA 存在但与注释里的版本标签不一致」——例如 pin 停在旧版本、或指到同名仓库的另一个
提交，此时文件看起来完全合规。

本脚本用 GitHub API 把每个 pin 与注释里的 tag 对拍：

- 非本地 `uses:` 缺少 40 位 SHA → 失败；
- pin 没有 `# <version>` 注释 → 失败（无法复核版本含义）；
- 注释里的 tag 在上游不存在 → 失败；
- tag 解析出的 commit 与 pin 不一致 → 失败。

用法：

    python -m scripts.check_action_pins --repository webees/immich-cn

退出码：``0`` 全部一致，``1`` 存在不一致，``2`` 配置或 API 错误。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from scripts.cleanup import CleanupError, GitHubClient

PIN = re.compile(
    r"^\s*(?:-\s*)?uses:\s*(?P<action>[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)@(?P<revision>\S+)(?:\s*#\s*(?P<version>\S+))?"
)
LOCAL_REFERENCE = re.compile(r"^\s*(?:-\s*)?uses:\s*\./")
SHA_REVISION = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class ActionPin:
    workflow: str
    line: int
    action: str
    revision: str
    version: str | None

    @property
    def label(self) -> str:
        return f"{self.action}@{self.revision[:12]}" + (f" # {self.version}" if self.version else "")


def parse_pins(paths: Iterable[Path]) -> tuple[list[ActionPin], list[str]]:
    """返回 (pins, errors)；errors 收集格式层面的问题，不需要联网。"""
    pins: list[ActionPin] = []
    errors: list[str] = []
    for path in sorted(paths):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "uses:" not in line or LOCAL_REFERENCE.match(line):
                continue
            match = PIN.match(line)
            if not match:
                errors.append(f"{path}:{number} 无法解析 uses 行：{line.strip()!r}")
                continue
            pin = ActionPin(
                workflow=path.name,
                line=number,
                action=match.group("action"),
                revision=match.group("revision"),
                version=match.group("version"),
            )
            if not SHA_REVISION.match(pin.revision):
                errors.append(f"{path}:{number} {pin.action} 未固定到 40 位 commit SHA：{pin.revision!r}")
                continue
            if not pin.version:
                errors.append(f"{path}:{number} {pin.label} 缺少 `# <version>` 注释，无法复核版本含义")
                continue
            pins.append(pin)
    if not pins and not errors:
        errors.append("没有解析到任何 Action pin，护栏可能已失效")
    return pins, errors


def check_pins(pins: Iterable[ActionPin], resolve: Callable[[str, str], str | None]) -> list[str]:
    """用 `resolve(action_repo, tag) -> commit_sha|None` 对拍每个 pin。"""
    errors: list[str] = []
    for pin in pins:
        if pin.version is None:  # parse_pins 已经过滤，这里兜底避免静默跳过
            errors.append(f"{pin.workflow}:{pin.line} {pin.label} 缺少 `# <version>` 注释")
            continue
        commit = resolve(pin.action, pin.version)
        if commit is None:
            errors.append(f"{pin.workflow}:{pin.line} {pin.action} 的版本 tag {pin.version!r} 在上游不存在")
        elif commit != pin.revision:
            errors.append(
                f"{pin.workflow}:{pin.line} {pin.action}#{pin.version} 指向 {commit[:12]}，"
                f"但工作流固定的是 {pin.revision[:12]}"
            )
    return errors


def resolve_tag_commit(client: GitHubClient, action: str, tag: str) -> str | None:
    """把 `owner/repo` + tag 解析成 commit SHA（自动解引用 annotated tag）。"""
    try:
        payload = client._request("GET", f"/repos/{action}/git/ref/tags/{tag}", allow_not_found=True)
    except CleanupError as error:
        raise CleanupError(f"查询 {action}@{tag} 失败：{error}") from error
    if not isinstance(payload, dict):
        return None
    obj = payload.get("object")
    if not isinstance(obj, dict):
        return None
    sha = str(obj.get("sha") or "")
    if obj.get("type") == "tag" and sha:
        tag_payload = client._request("GET", f"/repos/{action}/git/tags/{sha}")
        if isinstance(tag_payload, dict) and isinstance(tag_payload.get("object"), dict):
            return str(tag_payload["object"].get("sha") or "") or None
        return None
    return sha or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workflows", type=Path, default=Path(".github/workflows"))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "webees/immich-cn"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "")
    args = parser.parse_args(argv)

    if not args.workflows.is_dir():
        print(f"::error::找不到工作流目录：{args.workflows}", file=sys.stderr)
        return 2
    paths = sorted(args.workflows.glob("*.yml"))
    if not paths:
        print(f"::error::{args.workflows} 下没有工作流文件", file=sys.stderr)
        return 2

    pins, errors = parse_pins(paths)
    if not errors:
        try:
            client = GitHubClient(args.repository, args.token)
            errors = check_pins(pins, lambda action, tag: resolve_tag_commit(client, action, tag))
        except CleanupError as error:
            print(f"::error::{error}", file=sys.stderr)
            return 2

    for pin in pins:
        print(f"[OK]   {pin.workflow}:{pin.line} {pin.label}")
    if errors:
        for error in errors:
            print(f"[!!] {error}")
        print(f"Action pin 校验失败：{len(errors)} 项")
        return 1
    print(f"Action pin 校验通过：{len(pins)} 个固定引用与上游 tag 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
