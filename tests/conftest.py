"""pytest 夹具。"""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_cn.config import BuildOptions
from tests.synthetic import create_synthetic_sources


@pytest.fixture
def synthetic_sources(tmp_path: Path) -> Path:
    """构造 sources 目录，覆盖直辖市、地级市、区县、乡镇、香港与境外数据。"""
    work_dir = tmp_path / "build"
    return create_synthetic_sources(work_dir, work_dir / "i18n-iso-countries" / "langs")


@pytest.fixture
def build_options(tmp_path: Path, synthetic_sources: Path) -> BuildOptions:
    return BuildOptions(
        work_dir=tmp_path / "build",
        dist_dir=tmp_path / "dist",
        cache_dir=tmp_path / "cache",
        config_dir=Path(__file__).resolve().parent.parent / "config",
        extra_countries=("CN",),
        patterns=("{admin_2}", "{admin_2} {admin_3}"),
        provider="offline",
        skip_fetch=True,
    )
