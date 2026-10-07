"""审计账本一致性校验器的行为测试：汇总必须能由明细复算。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.check_audit_ledger import consecutive_clean, main, summarize, validate


def entry(round_number: int, verdict: str, severity: str | None = None) -> dict[str, Any]:
    return {"round": round_number, "verdict": verdict, "severity": severity, "focus": f"focus-{round_number}"}


def ledger(**overrides: Any) -> dict[str, Any]:
    history = [
        entry(1, "findings", "P1"),
        entry(2, "findings", "P1/P2"),
        entry(3, "clean"),
        entry(4, "wait"),
        entry(5, "clean"),
    ]
    base: dict[str, Any] = {
        "round": 5,
        "consecutive_clean": 1,
        "totals": summarize(history),
        "status": "active",
        "clean_rounds_required": 50,
        "history": history,
    }
    base.update(overrides)
    return base


def test_summarize_counts_by_round() -> None:
    """P1/P2 同时计入 P1 与 P2；clean 与 findings 各自计数。"""
    derived = summarize(ledger()["history"])
    assert derived == {"findings": 2, "clean_rounds": 2, "p0": 0, "p1": 2, "p2": 1, "p3": 0}


def test_consecutive_clean_counts_trailing_run() -> None:
    assert consecutive_clean(ledger()["history"]) == 1
    assert consecutive_clean([entry(1, "clean"), entry(2, "clean")]) == 2
    assert consecutive_clean([entry(1, "clean"), entry(2, "findings", "P2")]) == 0


def test_consistent_ledger_passes() -> None:
    assert validate(ledger()) == []


def test_declared_totals_must_match_history() -> None:
    """这是真实事故的负向控制：声明的 findings 与明细脱钩必须被发现。"""
    bad = ledger(totals={**summarize(ledger()["history"]), "findings": 99})
    errors = validate(bad)
    assert any("totals.findings" in error for error in errors), errors


def test_stale_clean_rounds_is_rejected() -> None:
    bad = ledger(totals={**summarize(ledger()["history"]), "clean_rounds": 71})
    errors = validate(bad)
    assert any("totals.clean_rounds" in error for error in errors), errors


def test_round_must_equal_history_max() -> None:
    errors = validate(ledger(round=4))
    assert any("round=4" in error for error in errors), errors


def test_duplicate_and_unordered_rounds_are_rejected() -> None:
    duplicate = ledger(history=[entry(1, "clean"), entry(1, "clean")], round=1, consecutive_clean=2)
    assert any("重复 round" in error for error in validate(duplicate))
    unordered = ledger(history=[entry(2, "clean"), entry(1, "clean")], round=2, consecutive_clean=2)
    assert any("严格递增" in error for error in validate(unordered))


def test_consecutive_clean_must_match_history() -> None:
    errors = validate(ledger(consecutive_clean=7))
    assert any("consecutive_clean" in error for error in errors), errors


def test_unknown_verdict_and_missing_severity_are_rejected() -> None:
    unknown = ledger(history=[entry(1, "maybe")], round=1, consecutive_clean=0, totals=summarize([]))
    assert any("verdict 非法" in error for error in validate(unknown))
    missing = ledger(
        history=[entry(1, "findings")], round=1, consecutive_clean=0, totals=summarize([entry(1, "findings")])
    )
    assert any("没有 severity" in error for error in validate(missing))


def test_severity_on_clean_entry_is_rejected() -> None:
    history = [entry(1, "clean", "P2")]
    errors = validate(ledger(history=history, round=1, consecutive_clean=1, totals=summarize(history)))
    assert any("却带了 severity" in error for error in errors), errors


def test_cli_reports_missing_file_and_bad_json(tmp_path: Path) -> None:
    assert main(["--path", str(tmp_path / "absent.json")]) == 2
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert main(["--path", str(broken)]) == 2


def test_cli_passes_on_consistent_ledger_and_fails_on_drift(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(ledger(), ensure_ascii=False), encoding="utf-8")
    assert main(["--path", str(good)]) == 0

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(ledger(consecutive_clean=42), ensure_ascii=False), encoding="utf-8")
    assert main(["--path", str(bad)]) == 1
