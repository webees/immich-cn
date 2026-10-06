"""CLI 默认值必须与库默认值一致。

同一语义的默认值若在 CLI 与库中各写一份，改动其一时会静默分叉：命令行用户与
直接调用库的用户会得到不同行为，而所有测试仍可能通过。
"""

from __future__ import annotations

import inspect
from pathlib import Path

from immich_cn.cli import build_parser
from immich_cn.config import DEFAULT_EXTRA_COUNTRIES, DEFAULT_PATTERNS, BuildOptions
from immich_cn.verify import verify_geodata


def test_build_options_defaults_match_cli() -> None:
    args = build_parser().parse_args(["all"])
    defaults = BuildOptions()

    assert args.work_dir == defaults.work_dir
    assert args.dist_dir == defaults.dist_dir
    assert args.cache_dir == defaults.cache_dir
    assert args.config_dir == defaults.config_dir
    assert args.provider == defaults.provider
    assert args.chinese_variant == defaults.chinese_variant
    assert args.min_population == defaults.min_population
    assert tuple(item.strip() for item in args.extra_countries.split(",") if item.strip()) == tuple(
        DEFAULT_EXTRA_COUNTRIES
    )
    assert tuple(item.strip() for item in args.patterns.split(",") if item.strip()) == tuple(DEFAULT_PATTERNS)


def test_verify_cli_threshold_matches_library_default() -> None:
    args = build_parser().parse_args(["verify", str(Path("build/geodata"))])
    signature = inspect.signature(verify_geodata)
    assert args.min_cn_ratio == signature.parameters["min_cn_cjk_ratio"].default
