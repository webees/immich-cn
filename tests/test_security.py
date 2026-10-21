from __future__ import annotations

import re
from pathlib import Path

DATA_BASE = re.compile(
    r"^ARG BASE_IMAGE=(?P<image>[^@\s]+@sha256:(?P<digest>[0-9a-f]{64}))$",
    re.IGNORECASE,
)
FROM_BASE = re.compile(r"^FROM \$\{BASE_IMAGE\}(?:\s+AS\s+\S+)?$", re.IGNORECASE)
DATA_BASE_REGISTRIES = {
    "public.ecr.aws/docker/library/alpine:3.24",
    "mirror.gcr.io/library/alpine:3.24",
}


def test_data_image_base_is_digest_pinned() -> None:
    """数据镜像允许切换镜像源，但所有来源必须共享固定摘要。"""
    path = Path(__file__).resolve().parent.parent / "docker" / "geodata.Dockerfile"
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    bases = [match for line in lines if (match := DATA_BASE.fullmatch(line))]
    from_lines = [line for line in lines if line.startswith("FROM ")]
    assert len(bases) == 1
    assert from_lines == ["FROM ${BASE_IMAGE}"]
    assert FROM_BASE.fullmatch(from_lines[0])
    image = bases[0].group("image")
    registry = image.split("@", 1)[0]
    assert registry in DATA_BASE_REGISTRIES
    assert bases[0].group("digest") == "294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6"


def test_server_image_declares_combined_license() -> None:
    """server 覆盖镜像包含上游 Immich 代码，不能只声明 MIT。"""
    path = Path(__file__).resolve().parent.parent / "docker" / "immich.Dockerfile"
    text = path.read_text(encoding="utf-8")
    assert 'org.opencontainers.image.licenses="AGPL-3.0-only AND MIT"' in text


def test_server_image_accepts_resolved_base_digest() -> None:
    """server 构建必须允许把 tag 解析成 tag@digest，降低基础镜像漂移风险。"""
    path = Path(__file__).resolve().parent.parent / "docker" / "immich.Dockerfile"
    text = path.read_text(encoding="utf-8")
    assert "ARG IMMICH_BASE_DIGEST=" in text
    assert "FROM ${IMMICH_BASE}:${IMMICH_VERSION}${IMMICH_BASE_DIGEST}" in text


def test_data_image_avoids_redundant_package_and_chmod_layers() -> None:
    """数据镜像应使用 Alpine 自带工具和 COPY --chmod，避免额外包与镜像层。"""
    path = Path(__file__).resolve().parent.parent / "docker" / "geodata.Dockerfile"
    text = path.read_text(encoding="utf-8")
    assert "apk add" not in text
    assert "RUN chmod" not in text
    assert text.count("COPY --chmod=0755") == 2
