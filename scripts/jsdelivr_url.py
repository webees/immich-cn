"""生成可配置的 jsDelivr GitHub 文件 URL。

默认使用中国加速候选 cdn.jsdmirror.com；用户可用
``IMMICH_CN_JSDELIVR_BASE`` 或 ``--base`` 切换到其他可信节点。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

DEFAULT_JSDELIVR_BASE = "https://cdn.jsdmirror.com"
JSDELIVR_FALLBACKS = (
    "https://cdn.jsdelivr.net",
    "https://gcore.jsdelivr.net",
    "https://fastly.jsdelivr.net",
    "https://cdn.jsdelivr.us",
    "https://jsd.onmicrosoft.cn",
)


def normalize_base(value: str) -> str:
    base = value.strip().rstrip("/")
    if not base.startswith(("https://", "http://")):
        raise ValueError(f"CDN base 必须是 http(s) URL：{value!r}")
    return base


def build_url(base: str, repo: str, ref: str, path: str) -> str:
    normalized_base = normalize_base(base)
    normalized_repo = repo.strip().strip("/")
    normalized_ref = ref.strip()
    normalized_path = path.strip().lstrip("/")
    if not normalized_repo or "/" not in normalized_repo:
        raise ValueError("--repo 必须使用 owner/repo 格式")
    if not normalized_ref:
        raise ValueError("--ref 不能为空")
    if not normalized_path:
        raise ValueError("--path 不能为空")
    return f"{normalized_base}/gh/{normalized_repo}@{normalized_ref}/{normalized_path}"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("IMMICH_CN_JSDELIVR_BASE", DEFAULT_JSDELIVR_BASE))
    parser.add_argument("--repo", default="webees/immich-cn")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--path", required=True, help="仓库内的文件路径")
    parser.add_argument("--json", action="store_true", help="输出 primary / fallbacks JSON")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        primary = build_url(args.base, args.repo, args.ref, args.path)
        fallbacks = [
            build_url(base, args.repo, args.ref, args.path)
            for base in JSDELIVR_FALLBACKS
            if normalize_base(base) != normalize_base(args.base)
        ]
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"primary": primary, "fallbacks": fallbacks}, ensure_ascii=False, indent=2))
    else:
        print(primary)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
