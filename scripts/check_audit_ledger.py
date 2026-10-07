"""校验审计账本自身的一致性。

审计账本（``work/audit/state.json``，发布在 ``audit`` 分支）是「连续 N 轮 clean」这一
结论的唯一证据。2026-10-07 复核发现账本的累计值无法由自身 history 复算：声明的
``findings`` 是 184，而 history 里只有 170 条 findings；``clean_rounds`` 声明 71，
实际是 72。汇总数字一旦和明细脱钩，最终 ``ACHIEVED`` 就无法被第三方复核。

本脚本把口径固定成**按轮次计数**，并要求每个汇总值都能从 history 推导：

- ``round`` = history 里最大的 round，且各 round 唯一、按列表顺序严格递增；
- ``totals.findings`` = verdict 为 ``findings`` 的条目数；
- ``totals.clean_rounds`` = verdict 为 ``clean`` 的条目数；
- ``totals.p0/p1/p2/p3`` = severity 里包含该级别的条目数（``P1/P2`` 同时计入两者）；
- ``consecutive_clean`` = 从最后一轮向前连续 ``clean`` 的条目数。

用法：

    python scripts/check_audit_ledger.py --path work/audit/state.json

退出码 ``0`` 表示账本自洽，``1`` 表示存在不一致，``2`` 表示文件缺失或不是合法 JSON。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SEVERITY_LEVELS = ("p0", "p1", "p2", "p3")
VALID_VERDICTS = ("clean", "findings", "wait")
#: 不计入任何结论、但必须存在的元数据键
REQUIRED_KEYS = ("round", "consecutive_clean", "totals", "status", "clean_rounds_required", "history")


def summarize(history: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """按文档口径从 history 复算所有汇总值。"""
    totals = {"findings": 0, "clean_rounds": 0, "p0": 0, "p1": 0, "p2": 0, "p3": 0}
    for entry in history:
        verdict = entry.get("verdict")
        if verdict == "findings":
            totals["findings"] += 1
        elif verdict == "clean":
            totals["clean_rounds"] += 1
        severity = str(entry.get("severity") or "")
        for level in SEVERITY_LEVELS:
            if level.upper() in severity.upper():
                totals[level] += 1
    return totals


def consecutive_clean(history: Sequence[Mapping[str, Any]]) -> int:
    """从最后一轮向前数连续 clean 的条目数。"""
    streak = 0
    for entry in reversed(history):
        if entry.get("verdict") != "clean":
            break
        streak += 1
    return streak


def validate(ledger: Mapping[str, Any]) -> list[str]:
    """返回账本不一致项；空列表表示自洽。"""
    errors: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in ledger:
            errors.append(f"账本缺少必需字段：{key}")
    if errors:
        return errors

    history = ledger["history"]
    if not isinstance(history, list) or not history:
        return ["history 必须是非空数组"]

    rounds: list[Any] = []
    for index, entry in enumerate(history, start=1):
        if not isinstance(entry, dict):
            errors.append(f"history 第 {index} 项不是对象")
            continue
        round_number = entry.get("round")
        if not isinstance(round_number, int) or round_number <= 0:
            errors.append(f"history 第 {index} 项的 round 不是正整数：{round_number!r}")
        else:
            rounds.append(round_number)
        verdict = entry.get("verdict")
        if verdict not in VALID_VERDICTS:
            errors.append(f"history 第 {index} 项的 verdict 非法：{verdict!r}")
        severity = entry.get("severity")
        if verdict == "findings" and not severity:
            errors.append(f"history 第 {index} 项是 findings 但没有 severity")
        if verdict in ("clean", "wait") and severity:
            errors.append(f"history 第 {index} 项是 {verdict} 却带了 severity：{severity!r}")
        if not entry.get("focus"):
            errors.append(f"history 第 {index} 项缺少 focus")
    if errors:
        return errors

    if len(set(rounds)) != len(rounds):
        duplicates = sorted({item for item in rounds if rounds.count(item) > 1})
        errors.append(f"history 存在重复 round：{duplicates}")
    if rounds != sorted(rounds):
        errors.append("history 的 round 不是按顺序严格递增")
    if isinstance(ledger["round"], int) and rounds and ledger["round"] != max(rounds):
        errors.append(f"round={ledger['round']} 与 history 最大轮次 {max(rounds)} 不一致")

    derived = summarize(history)
    declared = ledger["totals"]
    if not isinstance(declared, dict):
        errors.append("totals 必须是对象")
    else:
        for key, value in derived.items():
            if declared.get(key) != value:
                errors.append(f"totals.{key} 声明为 {declared.get(key)!r}，由 history 复算为 {value}")

    streak = consecutive_clean(history)
    if ledger["consecutive_clean"] != streak:
        errors.append(f"consecutive_clean 声明为 {ledger['consecutive_clean']!r}，由 history 复算为 {streak}")

    required = ledger["clean_rounds_required"]
    if not isinstance(required, int) or required <= 0:
        errors.append(f"clean_rounds_required 必须是正整数：{required!r}")
    if not isinstance(ledger["status"], str) or not ledger["status"]:
        errors.append("status 必须是非空字符串")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", type=Path, default=Path("work/audit/state.json"))
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"::error::找不到审计账本：{args.path}", file=sys.stderr)
        return 2
    try:
        ledger = json.loads(args.path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        print(f"::error::审计账本不是合法 JSON：{error}", file=sys.stderr)
        return 2
    if not isinstance(ledger, dict):
        print("::error::审计账本顶层必须是对象", file=sys.stderr)
        return 2

    errors = validate(ledger)
    if errors:
        for error in errors:
            print(f"[!!] {error}")
        print(f"审计账本一致性检查失败：{len(errors)} 项")
        return 1
    derived = summarize(ledger["history"])
    print(
        "审计账本一致：round={round} clean_rounds={clean_rounds} consecutive_clean={streak} "
        "findings={findings} p1={p1} p2={p2} p3={p3}".format(
            round=ledger["round"], streak=ledger["consecutive_clean"], **derived
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
