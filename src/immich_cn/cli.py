"""``immich-cn`` 命令行入口。"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from immich_cn import __version__
from immich_cn.build import fetch_sources, run_build
from immich_cn.config import DEFAULT_EXTRA_COUNTRIES, DEFAULT_PATTERNS, BuildOptions
from immich_cn.errors import ImmichCnError
from immich_cn.fingerprint import fingerprint_from_file
from immich_cn.logging_setup import configure, get_logger
from immich_cn.package import package_all
from immich_cn.verify import assert_valid, format_results, verify_geodata

logger = get_logger("cli")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_VERIFY = 2


def _add_common_options(parser: argparse.ArgumentParser, *, with_defaults: bool) -> None:
    """把通用选项同时挂到主命令与子命令上，两种书写顺序都能生效。"""

    def default(value: object) -> object:
        return value if with_defaults else argparse.SUPPRESS

    parser.add_argument("--work-dir", type=Path, default=default(Path("build")), help="中间产物目录（默认 build）")
    parser.add_argument("--dist-dir", type=Path, default=default(Path("dist")), help="发布制品目录（默认 dist）")
    parser.add_argument("--cache-dir", type=Path, default=default(Path(".cache/immich-cn")), help="下载缓存目录")
    parser.add_argument("--config-dir", type=Path, default=default(Path("config")), help="配置目录")
    parser.add_argument(
        "--provider",
        choices=("offline", "amap", "nominatim", "auto"),
        default=default("offline"),
        help="反向地理编码 provider（默认 offline，无需任何密钥）",
    )
    parser.add_argument(
        "--chinese-variant",
        choices=("hans", "hant"),
        default=default("hans"),
        help="输出字形：hans 简体（默认）/ hant 繁体",
    )
    parser.add_argument(
        "--extra-countries",
        default=default(",".join(DEFAULT_EXTRA_COUNTRIES)),
        help="需要附带国家全量 dump 的地区，逗号分隔",
    )
    parser.add_argument(
        "--patterns",
        default=default(",".join(DEFAULT_PATTERNS)),
        help="需要打包的展示粒度，逗号分隔",
    )
    parser.add_argument("--min-population", type=int, default=default(100), help="非 full 变体的最小人口阈值")
    parser.add_argument("--jobs", type=int, default=default(0), help="打包并发度，0 表示自动")
    parser.add_argument("--force", action="store_true", default=default(False), help="强制重新下载全部数据源")
    parser.add_argument(
        "--revalidate",
        action="store_true",
        default=default(False),
        help="下载前用 ETag/Last-Modified 校验上游是否更新（每日自动更新建议开启）",
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        default=default(False),
        help="跳过下载，直接使用 --work-dir/sources 中已存在的数据源",
    )
    parser.add_argument("--keep-raw", action="store_true", default=default(False), help="保留解压后的原始大文件")
    parser.add_argument("--quiet", action="store_true", default=default(False), help="只输出警告与错误")
    parser.add_argument("--clean", action="store_true", default=default(False), help="执行前清空 work/dist 目录")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="immich-cn",
        description="为 Immich 构建中文反向地理编码数据的自动化流水线",
    )
    parser.add_argument("--version", action="version", version=f"immich-cn {__version__}")
    _add_common_options(parser, with_defaults=True)

    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("fetch", "仅下载并解压上游数据源"),
        ("build", "下载并构建 geodata 目录"),
        ("all", "执行 fetch + build + package"),
    ):
        child = sub.add_parser(name, help=help_text)
        _add_common_options(child, with_defaults=False)

    verify = sub.add_parser("verify", help="校验 geodata 目录")
    verify.add_argument("path", type=Path, help="待校验的 geodata 目录")
    verify.add_argument("--min-cn-ratio", type=float, default=0.90, help="中国记录的中文名称覆盖率下限")

    fingerprint = sub.add_parser("fingerprint", help="打印 manifest.json 的数据指纹")
    fingerprint.add_argument("manifest", type=Path, help="manifest.json 路径")
    return parser


def _options(args: argparse.Namespace) -> BuildOptions:
    extra = tuple(item.strip().upper() for item in str(args.extra_countries).split(",") if item.strip())
    patterns = tuple(item.strip() for item in str(args.patterns).split(",") if item.strip())
    from os import cpu_count

    jobs = args.jobs or max(1, min(8, cpu_count() or 2))
    return BuildOptions(
        work_dir=args.work_dir,
        dist_dir=args.dist_dir,
        cache_dir=args.cache_dir,
        config_dir=args.config_dir,
        extra_countries=extra or DEFAULT_EXTRA_COUNTRIES,
        patterns=patterns or DEFAULT_PATTERNS,
        min_population=args.min_population,
        provider=args.provider,
        chinese_variant=args.chinese_variant,
        force_refresh=args.force,
        revalidate=args.revalidate,
        keep_raw=args.keep_raw,
        skip_fetch=args.skip_fetch,
        jobs=jobs,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure("INFO", quiet=args.quiet)

    if args.command == "verify":
        return _run_verify(args)
    if args.command == "fingerprint":
        try:
            print(fingerprint_from_file(str(args.manifest)))
        except (OSError, ValueError) as error:
            logger.error("%s", error)
            return EXIT_ERROR
        return EXIT_OK

    options = _options(args)
    try:
        if args.clean:
            for path in (options.work_dir, options.dist_dir):
                if path.exists():
                    logger.warning("清理目录 %s", path)
                    shutil.rmtree(path)
        if args.command == "fetch":
            fetch_sources(options)
            return EXIT_OK
        if args.command == "build":
            result = run_build(options)
            logger.info("构建完成：%s（%d 条记录）", result.geodata_dir, result.stats.output_places)
            return EXIT_OK
        if args.command == "all":
            result = run_build(options)
            package = package_all(options, result)
            logger.info("全部完成：%s", package.dist_dir)
            results = verify_geodata(result.geodata_dir)
            print(format_results(results))
            assert_valid(results)
            return EXIT_OK
    except ImmichCnError as error:
        logger.error("%s", error)
        return EXIT_ERROR

    parser.print_help()
    return EXIT_ERROR


def _run_verify(args: argparse.Namespace) -> int:
    results = verify_geodata(args.path, min_cn_cjk_ratio=args.min_cn_ratio)
    print(format_results(results))
    try:
        assert_valid(results)
    except ImmichCnError:
        return EXIT_VERIFY
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
