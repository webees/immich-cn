"""生成一套合成数据并跑完整流水线，用于 CI 与本地 Docker 冒烟测试。

该脚本只用于验证流水线的可运行性，生成的数据不是真实地名数据。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tests.synthetic import create_synthetic_sources

from immich_cn.packaging import package_all
from immich_cn.pipeline import run_build
from immich_cn.settings import DEFAULT_PATTERNS, BuildOptions
from immich_cn.validation import assert_valid, verify_geodata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=Path("build"))
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument("--patterns", default=",".join(DEFAULT_PATTERNS))
    args = parser.parse_args(argv)

    work_dir: Path = args.work_dir
    create_synthetic_sources(work_dir, work_dir / "i18n-iso-countries" / "langs")
    options = BuildOptions(
        work_dir=work_dir,
        dist_dir=args.dist_dir,
        cache_dir=work_dir / "cache",
        config_dir=args.config_dir,
        extra_countries=("CN",),
        patterns=tuple(item.strip() for item in args.patterns.split(",") if item.strip()),
        provider="offline",
        skip_fetch=True,
    )
    result = run_build(options)
    package_all(options, result)
    assert_valid(verify_geodata(result.geodata_dir))
    print(f"smoke data ready: {options.dist_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
