from __future__ import annotations

import zipfile
from pathlib import Path

import httpx
import pytest

from immich_cn.build import _materialize
from immich_cn.config import BuildOptions, SourceSpec
from immich_cn.errors import SourceError
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


def test_fetcher_revalidate_keeps_cached_content_on_304(tmp_path: Path) -> None:
    calls: list[str | None] = []
    state = {"body": b"v1", "etag": '"e1"'}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("if-none-match"))
        if request.headers.get("if-none-match") == state["etag"]:
            return httpx.Response(304)
        return httpx.Response(200, content=state["body"], headers={"etag": state["etag"]})

    spec = SourceSpec(name="demo", url="https://example.com/demo.txt", filename="demo.txt")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with Fetcher(tmp_path / "cache", client=client) as fetcher:
        first = fetcher.fetch(spec)
    with Fetcher(tmp_path / "cache", revalidate=True, client=client) as fetcher:
        second = fetcher.fetch(spec)

    assert calls == [None, '"e1"']
    assert second.record.sha256 == first.record.sha256
    assert (tmp_path / "cache" / "demo.txt").read_bytes() == b"v1"


def test_fetcher_revalidate_downloads_when_upstream_changed(tmp_path: Path) -> None:
    state = {"body": b"v1", "etag": '"e1"'}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == state["etag"]:
            return httpx.Response(304)
        return httpx.Response(200, content=state["body"], headers={"etag": state["etag"]})

    spec = SourceSpec(name="demo", url="https://example.com/demo.txt", filename="demo.txt")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with Fetcher(tmp_path / "cache", client=client) as fetcher:
        first = fetcher.fetch(spec)

    state["body"] = b"v2-updated"
    state["etag"] = '"e2"'
    with Fetcher(tmp_path / "cache", revalidate=True, client=client) as fetcher:
        second = fetcher.fetch(spec)

    assert second.record.sha256 != first.record.sha256
    assert second.record.etag == '"e2"'
    assert (tmp_path / "cache" / "demo.txt").read_bytes() == b"v2-updated"


def test_fetcher_revalidate_falls_back_to_cache_on_error(tmp_path: Path) -> None:
    def ok(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"v1", headers={"etag": '"e1"'})

    def broken(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    spec = SourceSpec(name="demo", url="https://example.com/demo.txt", filename="demo.txt")
    with Fetcher(tmp_path / "cache", client=httpx.Client(transport=httpx.MockTransport(ok))) as fetcher:
        cached = fetcher.fetch(spec)
    with Fetcher(
        tmp_path / "cache",
        revalidate=True,
        client=httpx.Client(transport=httpx.MockTransport(broken)),
    ) as fetcher:
        fallback = fetcher.fetch(spec)

    assert fallback.record.sha256 == cached.record.sha256
    assert (tmp_path / "cache" / "demo.txt").read_bytes() == b"v1"


def test_fetcher_revalidate_ignores_empty_body(tmp_path: Path) -> None:
    """上游返回 200 但正文为空时必须保留本地缓存，不能被"假成功"覆盖。"""

    def ok(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"v1", headers={"etag": '"e1"'})

    def empty(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"", headers={"etag": '"e2"'})

    spec = SourceSpec(name="demo", url="https://example.com/demo.txt", filename="demo.txt")
    with Fetcher(tmp_path / "cache", client=httpx.Client(transport=httpx.MockTransport(ok))) as fetcher:
        cached = fetcher.fetch(spec)
    with Fetcher(
        tmp_path / "cache",
        revalidate=True,
        client=httpx.Client(transport=httpx.MockTransport(empty)),
    ) as fetcher:
        result = fetcher.fetch(spec)

    assert result.record.sha256 == cached.record.sha256
    assert (tmp_path / "cache" / "demo.txt").read_bytes() == b"v1"


def test_fetcher_rejects_truncated_download(tmp_path: Path) -> None:
    """Content-Length 与实际字节不一致时必须失败，避免把截断内容当成成功。"""

    def truncated(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"short", headers={"content-length": "100"})

    spec = SourceSpec(name="demo", url="https://example.com/demo.txt", filename="demo.txt")
    with (
        Fetcher(
            tmp_path / "cache",
            retries=1,
            client=httpx.Client(transport=httpx.MockTransport(truncated)),
        ) as fetcher,
        pytest.raises(SourceError) as excinfo,
    ):
        fetcher.fetch(spec)
    assert "下载不完整" in str(excinfo.value)
    assert not (tmp_path / "cache" / "demo.txt").exists()


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
