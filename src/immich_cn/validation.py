"""数据制品校验：在发布前拦截明显损坏或不完整的构建结果。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from immich_cn.errors import VerifyError
from immich_cn.localization import has_cjk
from immich_cn.logging_config import get_logger

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


def verify_geodata(
    directory: Path,
    *,
    min_cn_cjk_ratio: float = 0.90,
    min_hk_cjk_ratio: float = 0.99,
    min_cn_admin_ratio: float = 0.95,
    min_cn_admin2_code_ratio: float = 0.90,
    min_cn_admin2_resolved_ratio: float = 0.99,
) -> list[CheckResult]:
    """校验一个 geodata 目录。"""
    results: list[CheckResult] = []
    missing = [name for name in REQUIRED_FILES if not (directory / name).exists()]
    results.append(CheckResult("required-files", not missing, "缺少：" + ", ".join(missing) if missing else "全部存在"))
    if missing:
        return results

    results.append(_check_date(directory / "geodata-date.txt"))
    results.append(
        _check_admin(
            directory / "admin1CodesASCII.txt",
            "admin1",
            min_overall_ratio=0.5,
            min_country_ratio=min_cn_admin_ratio,
            regions=("CN.", "HK.", "MO.", "TW.", "JP."),
            # 日本有约 4% 的市名官方写法就是假名（如 たつの市），阈值单独放宽
            region_min_ratios={"JP.": 0.90},
        )
    )
    results.append(
        _check_admin(
            directory / "admin2Codes.txt",
            "admin2",
            min_overall_ratio=0.0,
            min_country_ratio=min_cn_admin_ratio,
            regions=("CN.", "TW.", "JP."),
            region_min_ratios={"JP.": 0.90},
        )
    )
    results.append(_check_country_info(directory / "countryInfo.txt"))
    results.append(_check_geojson(directory / "ne_10m_admin_0_countries.geojson"))
    admin2_codes = set(_load_admin_codes(directory / "admin2Codes.txt"))
    results.extend(
        _check_cities500(
            directory / "cities500.txt",
            min_cn_cjk_ratio=min_cn_cjk_ratio,
            min_hk_cjk_ratio=min_hk_cjk_ratio,
            min_cn_admin2_code_ratio=min_cn_admin2_code_ratio,
            min_cn_admin2_resolved_ratio=min_cn_admin2_resolved_ratio,
            admin2_codes=admin2_codes,
        )
    )
    return results


def _load_admin_codes(path: Path) -> dict[str, str]:
    codes: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) >= 4:
                codes[fields[0]] = fields[1]
    return codes


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


def _check_admin(
    path: Path,
    label: str,
    *,
    min_overall_ratio: float,
    min_country_ratio: float,
    country: str = "CN",
    regions: tuple[str, ...] = (),
    region_min_ratios: dict[str, float] | None = None,
) -> CheckResult:
    """校验行政层级表。

    除了整体中文覆盖率，还会单独校验 ``country`` 前缀下条目的中文覆盖率——
    否则当该国家条目只占全表很小比例时，整体比例无法发现汉化整体失效。
    """
    total = 0
    chinese = 0
    country_total = 0
    country_chinese = 0
    region_counts: dict[str, list[int]] = {region: [0, 0] for region in regions}
    bad = 0
    prefix = f"{country}."
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 4:
                bad += 1
                continue
            total += 1
            is_chinese = has_cjk(fields[1])
            if is_chinese:
                chinese += 1
            if fields[0].startswith(prefix):
                country_total += 1
                if is_chinese:
                    country_chinese += 1
            for region in regions:
                if fields[0].startswith(region):
                    region_counts[region][0] += 1
                    if is_chinese:
                        region_counts[region][1] += 1
    if bad:
        return CheckResult(label, False, f"{bad} 行字段不足")
    if total == 0:
        return CheckResult(label, False, "文件为空")
    overall = chinese / total
    detail = f"{total} 条，中文 {chinese} 条（{overall:.1%}）"
    if overall < min_overall_ratio:
        return CheckResult(label, False, f"{detail}，整体中文覆盖率低于 {min_overall_ratio:.0%}")
    if country_total == 0:
        return CheckResult(label, False, f"{detail}，未找到 {prefix}* 条目")
    country_ratio = country_chinese / country_total
    detail += f"；{country} 条目 {country_total} 条，中文 {country_chinese} 条（{country_ratio:.1%}）"
    if country_ratio < min_country_ratio:
        return CheckResult(label, False, f"{detail}，低于 {min_country_ratio:.0%}")
    for region, (count, chinese_count) in region_counts.items():
        if count == 0:
            return CheckResult(label, False, f"{detail}，未找到 {region}* 条目")
        region_ratio = chinese_count / count
        threshold = (region_min_ratios or {}).get(region, min_country_ratio)
        if region_ratio < threshold:
            return CheckResult(
                label,
                False,
                f"{region}* 条目 {count} 条，中文仅 {chinese_count} 条（{region_ratio:.1%}），低于 {threshold:.0%}",
            )
    return CheckResult(label, True, detail)


def _check_country_info(path: Path) -> CheckResult:
    total = 0
    chinese = 0
    bad = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 5:
                bad += 1
                continue
            total += 1
            if has_cjk(fields[4]):
                chinese += 1
    if total == 0:
        return CheckResult("countryInfo", False, f"没有可解析记录，字段异常 {bad} 条")
    ratio = chinese / total
    # 项目已通过 i18n 数据与人工覆盖保证所有当前国家/地区名称可用中文表达。
    return CheckResult(
        "countryInfo",
        bad == 0 and ratio >= 1.0,
        f"{total} 个国家/地区，中文 {chinese} 条（{ratio:.1%}），字段异常 {bad} 条",
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


def _check_cities500(
    path: Path,
    *,
    min_cn_cjk_ratio: float,
    min_hk_cjk_ratio: float = 0.99,
    min_cn_admin2_code_ratio: float,
    min_cn_admin2_resolved_ratio: float = 0.99,
    admin2_codes: set[str] | None = None,
) -> list[CheckResult]:
    total = 0
    bad = 0
    seen: set[int] = set()
    duplicates = 0
    cn_total = 0
    cn_chinese = 0
    hk_total = 0
    hk_chinese = 0
    cn_with_admin2 = 0
    cn_admin2_resolved = 0
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
            try:
                latitude = float(fields[4])
                longitude = float(fields[5])
            except ValueError:
                bad += 1
                continue
            if (
                not math.isfinite(latitude)
                or not math.isfinite(longitude)
                or not -90.0 <= latitude <= 90.0
                or not -180.0 <= longitude <= 180.0
            ):
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
                    if admin2_codes is None or f"CN.{fields[10]}.{fields[11]}" in admin2_codes:
                        cn_admin2_resolved += 1
            elif fields[8] == "HK":
                hk_total += 1
                if has_cjk(fields[1]):
                    hk_chinese += 1
    results = [
        CheckResult("cities500", bad == 0, f"{total} 条记录，字段异常 {bad} 条"),
        CheckResult("cities500-duplicates", duplicates == 0, f"重复 GeoNames ID {duplicates} 条"),
    ]
    cn_ratio = cn_chinese / cn_total if cn_total else 0.0
    results.append(
        CheckResult(
            "cities500-cn-cjk",
            cn_total > 0 and cn_ratio >= min_cn_cjk_ratio,
            f"中国记录 {cn_total} 条，中文名称 {cn_chinese} 条（{cn_ratio:.1%}）",
        )
    )
    if cn_total:
        admin_ratio = cn_with_admin2 / cn_total
        results.append(
            CheckResult(
                "cities500-cn-admin2",
                admin_ratio >= min_cn_admin2_code_ratio,
                f"中国记录 {cn_total} 条，带 admin2 代码 {cn_with_admin2} 条（{admin_ratio:.1%}）",
            )
        )
        # 仅"代码非空"并不足以说明数据可用：代码还必须在 admin2Codes.txt 中能解析出名称，
        # 否则 Immich 的 admin2Name 会是空值。这里做引用完整性检查。
        resolved_ratio = cn_admin2_resolved / max(cn_with_admin2, 1)
        results.append(
            CheckResult(
                "cities500-cn-admin2-resolvable",
                resolved_ratio >= min_cn_admin2_resolved_ratio,
                f"带 admin2 代码的中国记录 {cn_with_admin2} 条，可在 admin2Codes 解析 "
                f"{cn_admin2_resolved} 条（{resolved_ratio:.2%}）",
            )
        )
    hk_ratio = hk_chinese / hk_total if hk_total else 0.0
    results.append(
        CheckResult(
            "cities500-hk-cjk",
            hk_total > 0 and hk_ratio >= min_hk_cjk_ratio,
            f"香港记录 {hk_total} 条，中文名称 {hk_chinese} 条（{hk_ratio:.1%}）",
        )
    )
    return results


def format_results(results: list[CheckResult]) -> str:
    lines = []
    for result in results:
        lines.append(f"[{'OK' if result.passed else '!!'}] {result.name}: {result.detail}")
    return "\n".join(lines)
