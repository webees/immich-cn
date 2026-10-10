"""CLI 默认值必须与库默认值一致。

同一语义的默认值若在 CLI 与库中各写一份，改动其一时会静默分叉：命令行用户与
直接调用库的用户会得到不同行为，而所有测试仍可能通过。
"""

from __future__ import annotations

import inspect
import tomllib
from pathlib import Path

import pytest

from immich_cn import __version__
from immich_cn.cli import build_parser
from immich_cn.errors import ConfigError
from immich_cn.settings import (
    DEFAULT_EXTRA_COUNTRIES,
    DEFAULT_PATTERNS,
    BuildOptions,
    country_codes_env,
    positive_int_env,
)
from immich_cn.validation import verify_geodata


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


def test_zero_jobs_uses_auto_default() -> None:
    """`0` 在 CLI 与库入口都必须表示自动并发。"""
    assert BuildOptions(jobs=0).jobs == BuildOptions().jobs


def test_project_version_matches_runtime() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == project["project"]["version"]


def test_verify_cli_threshold_matches_library_default() -> None:
    args = build_parser().parse_args(["verify", str(Path("build/geodata"))])
    signature = inspect.signature(verify_geodata)
    assert args.min_cn_ratio == signature.parameters["min_cn_cjk_ratio"].default


def test_positive_int_env_rejects_non_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMICH_CN_TEST_POSITIVE_INT", "not-a-number")
    with pytest.raises(ConfigError, match="必须是整数"):
        positive_int_env("IMMICH_CN_TEST_POSITIVE_INT", 3)


def test_country_codes_env_normalizes_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMICH_CN_TEST_COUNTRIES", " cn, hk ,, ")
    assert country_codes_env("IMMICH_CN_TEST_COUNTRIES", ("TW",)) == ("CN", "HK")

    monkeypatch.setenv("IMMICH_CN_TEST_COUNTRIES", " , ")
    assert country_codes_env("IMMICH_CN_TEST_COUNTRIES", ("TW",)) == ("TW",)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"min_population": -1}, "min_population"),
        ({"jobs": -1}, "jobs"),
        ({"patterns": ()}, "至少需要"),
        ({"patterns": ("no-placeholder",)}, "admin_N"),
        ({"patterns": ("{admin_bad}",)}, "未知占位符"),
        ({"patterns": ("{admin_2} {admin_2}",)}, "重复占位符"),
    ],
)
def test_build_options_rejects_invalid_configuration(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        BuildOptions(**kwargs)
