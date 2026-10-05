from __future__ import annotations

import zipfile
from pathlib import Path

import httpx

from immich_cn.build import _materialize
from immich_cn.config import BuildOptions, SourceSpec
from immich_cn.http import Fetcher, sha256_bytes
from immich_cn.models import SourceRecord


def test_fetcher_caches_downloads(tmp_path: Path) -> None:
    payload = b"hello geonames"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200, content=payload, headers={"etag": '"abc"', "last-modified": "Wed, 01 Jan 2025 00:00:00 GMT"}
        )

    spec = SourceSpec(name="demo", url="https://example.com/demo.txt", filename="demo.txt")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with Fetcher(tmp_path / "cache", client=client) as fetcher:
        first = fetcher.fetch(spec)
        second = fetcher.fetch(spec)

    assert len(calls) == 1
    assert first.record.sha256 == sha256_bytes(payload)
    assert second.record.sha256 == first.record.sha256
    assert (tmp_path / "cache" / "demo.txt").read_bytes() == payload


def test_fetcher_force_refreshes(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append("x")
        return httpx.Response(200, content=b"v1")

    spec = SourceSpec(name="demo", url="https://example.com/demo.txt", filename="demo.txt")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with Fetcher(tmp_path / "cache", client=client) as fetcher:
        fetcher.fetch(spec)
    with Fetcher(tmp_path / "cache", force=True, client=client) as fetcher:
        fetcher.fetch(spec)
    assert len(calls) == 2


class _StubFetched:
    """最小的 FetchedSource 替身，避免为测试构造完整下载流程。"""

    def __init__(self, spec: SourceSpec, path: Path, digest: str) -> None:
        self.spec = spec
        self.path = path
        self.record = SourceRecord(name=spec.name, url=spec.url, sha256=digest, size_bytes=path.stat().st_size)


def test_materialize_reextracts_only_when_digest_changes(tmp_path: Path) -> None:
    archive = tmp_path / "cities500.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("cities500.txt", "v1\n")
    spec = SourceSpec(
        name="cities500",
        url="https://example.com/cities500.zip",
        filename="cities500.txt",
        members=("cities500.txt",),
    )
    options = BuildOptions(work_dir=tmp_path / "build", dist_dir=tmp_path / "dist")
    options.sources_dir.mkdir(parents=True, exist_ok=True)
    destination = options.sources_dir / "cities500.txt"

    fetched = _StubFetched(spec, archive, "digest-1")
    _materialize([fetched], options)  # type: ignore[list-item]
    assert destination.read_text(encoding="utf-8") == "v1\n"

    # 同摘要不会覆盖本地内容
    destination.write_text("tampered\n", encoding="utf-8")
    _materialize([fetched], options)  # type: ignore[list-item]
    assert destination.read_text(encoding="utf-8") == "tampered\n"

    # 摘要变化会重新解压
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("cities500.txt", "v2\n")
    fetched.record = SourceRecord(name=spec.name, url=spec.url, sha256="digest-2", size_bytes=archive.stat().st_size)
    _materialize([fetched], options)  # type: ignore[list-item]
    assert destination.read_text(encoding="utf-8") == "v2\n"
