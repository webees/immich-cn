from __future__ import annotations

import re
from pathlib import Path

DIGEST_PIN = re.compile(r"^FROM \S+@sha256:[0-9a-f]{64}(?:\s+AS\s+\S+)?$", re.IGNORECASE)


def test_data_image_base_is_digest_pinned() -> None:
    """数据镜像的基础镜像不能只依赖可重定向 tag。"""
    path = Path(__file__).resolve().parent.parent / "docker" / "geodata.Dockerfile"
    from_lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("FROM ")]
    assert from_lines
    assert all(DIGEST_PIN.fullmatch(line) for line in from_lines), from_lines
