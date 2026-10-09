from __future__ import annotations

import re
from pathlib import Path

DIGEST_PIN = re.compile(r"^FROM \S+@sha256:[0-9a-f]{64}(?:\s+AS\s+\S+)?$", re.IGNORECASE)


def test_data_image_base_is_digest_pinned() -> None:
    """数据镜像使用 Public ECR 的同一 Alpine 摘要，避开 Docker Hub 限流。"""
    path = Path(__file__).resolve().parent.parent / "docker" / "geodata.Dockerfile"
    from_lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("FROM ")]
    assert from_lines
    assert all(DIGEST_PIN.fullmatch(line) for line in from_lines), from_lines
    assert from_lines[0].startswith("FROM public.ecr.aws/docker/library/alpine:")
    assert not any(line.startswith("FROM alpine:") for line in from_lines)


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
