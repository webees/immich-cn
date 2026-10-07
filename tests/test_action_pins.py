"""Action pin 校验器的负向控制：格式与上游 tag 两方面都要能失败。"""

from __future__ import annotations

from pathlib import Path

from scripts.check_action_pins import ActionPin, check_pins, main, parse_pins

SHA = "a" * 40
OTHER = "b" * 40


def write_workflow(tmp_path: Path, body: str) -> Path:
    directory = tmp_path / "workflows"
    directory.mkdir(exist_ok=True)
    path = directory / "demo.yml"
    path.write_text(body, encoding="utf-8")
    return directory


def test_parse_pins_accepts_pinned_action_and_skips_local(tmp_path: Path) -> None:
    directory = write_workflow(
        tmp_path,
        "\n".join(
            [
                "jobs:",
                "  a:",
                "    steps:",
                f"      - uses: actions/checkout@{SHA} # v7",
                "      - uses: ./.github/workflows/_build-data.yml",
            ]
        ),
    )

    pins, errors = parse_pins(sorted(directory.glob("*.yml")))

    assert errors == []
    assert [pin.action for pin in pins] == ["actions/checkout"]
    assert pins[0].version == "v7"


def test_parse_pins_rejects_floating_tag(tmp_path: Path) -> None:
    directory = write_workflow(tmp_path, "      - uses: actions/checkout@v7 # v7\n")
    pins, errors = parse_pins(sorted(directory.glob("*.yml")))
    assert pins == []
    assert any("未固定到 40 位 commit SHA" in error for error in errors)


def test_parse_pins_requires_version_comment(tmp_path: Path) -> None:
    """没有版本注释就无法复核 pin 的含义，必须失败而不是当成合规。"""
    directory = write_workflow(tmp_path, f"      - uses: actions/checkout@{SHA}\n")
    pins, errors = parse_pins(sorted(directory.glob("*.yml")))
    assert pins == []
    assert any("缺少 `# <version>` 注释" in error for error in errors)


def test_parse_pins_flags_empty_result(tmp_path: Path) -> None:
    directory = write_workflow(tmp_path, "jobs: {}\n")
    pins, errors = parse_pins(sorted(directory.glob("*.yml")))
    assert pins == []
    assert any("护栏可能已失效" in error for error in errors)


def test_check_pins_passes_when_tag_matches() -> None:
    pin = ActionPin("ci.yml", 1, "actions/checkout", SHA, "v7")
    assert check_pins([pin], lambda _action, _tag: SHA) == []


def test_check_pins_detects_tag_drift() -> None:
    """真实风险：pin 停在旧版本，但注释写着新版本。"""
    pin = ActionPin("ci.yml", 1, "actions/checkout", SHA, "v7")
    errors = check_pins([pin], lambda _action, _tag: OTHER)
    assert any("指向" in error and "固定的是" in error for error in errors)


def test_check_pins_detects_missing_tag() -> None:
    pin = ActionPin("ci.yml", 1, "actions/checkout", SHA, "v99")
    errors = check_pins([pin], lambda _action, _tag: None)
    assert any("在上游不存在" in error for error in errors)


def test_cli_rejects_missing_workflow_directory(tmp_path: Path) -> None:
    assert main(["--workflows", str(tmp_path / "nope"), "--token", "x"]) == 2
