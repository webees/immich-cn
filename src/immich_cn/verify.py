"""数据制品校验：在发布前拦截明显损坏或不完整的构建结果。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from immich_cn.chinese import has_cjk
from immich_cn.errors import VerifyError
from immich_cn.logging_setup import get_logger

logger = get_logger("verify")

REQUIRED_FILES = (
    "admin1CodesASCII.txt",
    "admin2Codes.txt",
    "cities500.txt",
    "countryInfo.txt",
    "geodata-date.txt",
    "ne_10m_admin_0_countries.geojson",
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def verify_geodata(directory: Path, *, min_cn_cjk_ratio: float = 0.90) -> list[CheckResult]:
    """校验一个 geodata 目录。"""
    results: list[CheckResult] = []
    missing = [name for name in REQUIRED_FILES if not (directory / name).exists()]
    results.append(CheckResult("required-files", not missing, "缺少：" + ", ".join(missing) if missing else "全部存在"))
    if missing:
        return results

    results.append(_check_date(directory / "geodata-date.txt"))
    results.append(_check_admin(directory / "admin1CodesASCII.txt", "admin1", expect_chinese=True))
    results.append(_check_admin(directory / "admin2Codes.txt", "admin2", expect_chinese=False))
    results.append(_check_country_info(directory / "countryInfo.txt"))
    results.append(_check_geojson(directory / "ne_10m_admin_0_countries.geojson"))
    results.extend(_check_cities500(directory / "cities500.txt", min_cn_cjk_ratio=min_cn_cjk_ratio))
    return results


def assert_valid(results: list[CheckResult]) -> None:
    """任一检查失败时抛出 :class:`VerifyError`。"""
    failed = [result for result in results if not result.passed]
    for result in results:
        logger.log(
            20 if result.passed else 40,
            "%s %s",
            "PASS" if result.passed else "FAIL",
            f"{result.name}: {result.detail}",
        )
    if failed:
        raise VerifyError("；".join(f"{result.name}: {result.detail}" for result in failed))


def _check_date(path: Path) -> CheckResult:
    raw = path.read_text(encoding="utf-8").strip()
    try:
        datetime.fromisoformat(raw)
    except ValueError:
        return CheckResult("geodata-date", False, f"无法解析时间：{raw!r}")
    return CheckResult("geodata-date", True, raw)


def _check_admin(path: Path, label: str, *, expect_chinese: bool) -> CheckResult:
    total = 0
    chinese = 0
    bad = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 4:
                bad += 1
                continue
            total += 1
            if has_cjk(fields[1]):
                chinese += 1
    if bad:
        return CheckResult(label, False, f"{bad} 行字段不足")
    if total == 0:
        return CheckResult(label, False, "文件为空")
    ratio = chinese / total
    detail = f"{total} 条，中文 {chinese} 条（{ratio:.1%}）"
    if expect_chinese and ratio < 0.5:
        return CheckResult(label, False, detail + "，中文覆盖过低")
    return CheckResult(label, True, detail)


def _check_country_info(path: Path) -> CheckResult:
    total = 0
    chinese = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 5:
                continue
            total += 1
            if has_cjk(fields[4]):
                chinese += 1
    if total == 0:
        return CheckResult("countryInfo", False, "文件为空")
    ratio = chinese / total
    return CheckResult(
        "countryInfo",
        ratio >= 0.9,
        f"{total} 个国家/地区，中文 {chinese} 条（{ratio:.1%}）",
    )


def _check_geojson(path: Path) -> CheckResult:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        return CheckResult("natural-earth", False, f"无法解析：{error}")
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list) or not features:
        return CheckResult("natural-earth", False, "缺少 features")
    return CheckResult("natural-earth", True, f"{len(features)} 个要素")


def _check_cities500(path: Path, *, min_cn_cjk_ratio: float) -> list[CheckResult]:
    total = 0
    bad = 0
    seen: set[int] = set()
    duplicates = 0
    cn_total = 0
    cn_chinese = 0
    cn_with_admin2 = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 19:
                bad += 1
                continue
            total += 1
            try:
                geoname_id = int(fields[0])
            except ValueError:
                bad += 1
                continue
            if geoname_id in seen:
                duplicates += 1
            seen.add(geoname_id)
            if fields[8] == "CN":
                cn_total += 1
                if has_cjk(fields[1]):
                    cn_chinese += 1
                if fields[11]:
                    cn_with_admin2 += 1
    results = [
        CheckResult("cities500", bad == 0, f"{total} 条记录，字段异常 {bad} 条"),
        CheckResult("cities500-duplicates", duplicates == 0, f"重复 GeoNames ID {duplicates} 条"),
    ]
    if cn_total:
        ratio = cn_chinese / cn_total
        results.append(
            CheckResult(
                "cities500-cn-cjk",
                ratio >= min_cn_cjk_ratio,
                f"中国记录 {cn_total} 条，中文名称 {cn_chinese} 条（{ratio:.1%}）",
            )
        )
    return results


def format_results(results: list[CheckResult]) -> str:
    lines = []
    for result in results:
        lines.append(f"[{'OK' if result.passed else '!!'}] {result.name}: {result.detail}")
    return "\n".join(lines)
