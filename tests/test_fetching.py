from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import httpx
import pytest

from immich_cn.domain import SourceRecord
from immich_cn.errors import SourceError
from immich_cn.fetching import Fetcher, retry_delay, sha256_bytes
from immich_cn.pipeline import _materialize
from immich_cn.settings import BuildOptions, SourceSpec

# 以 root 运行时文件权限不生效，无法构造只读目录场景
requires_real_permissions = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root 不受文件权限限制",
)


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


def test_fetcher_detects_same_size_cache_corruption(tmp_path: Path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"good" if calls == 1 else b"new!")

    spec = SourceSpec(name="demo", url="https://example.com/demo.txt", filename="demo.txt")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    cache = tmp_path / "cache"
    with Fetcher(cache, client=client) as fetcher:
        fetcher.fetch(spec)

    target = cache / "demo.txt"
    target.write_bytes(b"evil")
    with Fetcher(cache, client=client) as fetcher:
        result = fetcher.fetch(spec)

    assert calls == 2
    assert result.path.read_bytes() == b"new!"


def test_fetcher_ignores_cache_when_pinned_digest_changed(tmp_path: Path) -> None:
    """固定摘要变化后，即使旧缓存自身校验通过也不能被信任。

    CI 的 `actions/cache` restore-key 故意很宽（`immich-cn-sources-<os>-`），会跨工具
    版本还原 `.cache/immich-cn`。这条负向控制证明「还原到旧缓存」不会让构建拿着旧内容
    还成功：命中缓存时会把文件摘要与 `spec.expected_sha256` 比对，不一致就删掉重下。
    """
    payload = b"stale cached bytes"
    changed = b"upstream changed!"
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, content=payload if len(calls) == 1 else changed)

    cache = tmp_path / "cache"
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with Fetcher(cache, client=client) as fetcher:
        fetcher.fetch(SourceSpec(name="demo", url="https://example.com/demo.txt", filename="demo.txt"))

    pinned = SourceSpec(
        name="demo",
        url="https://example.com/demo.txt",
        filename="demo.txt",
        expected_sha256=sha256_bytes(changed),
    )
    with Fetcher(cache, client=client) as fetcher:
        result = fetcher.fetch(pinned)

    assert len(calls) == 2, "固定摘要变化后必须重新下载，不能复用旧缓存"
    assert result.path.read_bytes() == changed
    assert result.record.sha256 == sha256_bytes(changed)


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


def test_fetcher_ignores_corrupt_meta_and_redownloads(tmp_path: Path) -> None:
    payload = b"fresh"
    calls: list[str] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append("x")
        return httpx.Response(200, content=payload)

    cache = tmp_path / "cache"
    (cache / ".meta").mkdir(parents=True)
    target = cache / "demo.txt"
    target.write_bytes(b"old")
    (cache / ".meta" / "demo.json").write_text(
        json.dumps({"url": "https://example.com/demo.txt", "sizeBytes": len(b"old")}),
        encoding="utf-8",
    )

    spec = SourceSpec(name="demo", url="https://example.com/demo.txt", filename="demo.txt")
    with Fetcher(
        cache,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as fetcher:
        result = fetcher.fetch(spec)

    assert calls == ["x"]
    assert result.path.read_bytes() == payload


def test_fetcher_redownloads_when_cached_file_is_larger_than_metadata(tmp_path: Path) -> None:
    payload = b"fresh"
    calls: list[str] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append("x")
        return httpx.Response(200, content=payload)

    cache = tmp_path / "cache"
    (cache / ".meta").mkdir(parents=True)
    target = cache / "demo.txt"
    target.write_bytes(b"stale-extra")
    (cache / ".meta" / "demo.json").write_text(
        json.dumps(
            {
                "url": "https://example.com/demo.txt",
                "sha256": sha256_bytes(b"stale"),
                "sizeBytes": len(b"stale"),
            }
        ),
        encoding="utf-8",
    )

    spec = SourceSpec(name="demo", url="https://example.com/demo.txt", filename="demo.txt")
    with Fetcher(
        cache,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as fetcher:
        result = fetcher.fetch(spec)

    assert calls == ["x"]
    assert result.path.read_bytes() == payload


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


def test_fetcher_revalidate_keeps_cache_on_truncated_body(tmp_path: Path) -> None:
    """强制校验时，Content-Length 与正文不一致不能覆盖健康缓存。"""

    def ok(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"A" * 20, headers={"content-length": "20", "etag": '"e1"'})

    def truncated(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"A" * 10, headers={"content-length": "20", "etag": '"e2"'})

    spec = SourceSpec(name="demo", url="https://example.com/demo.bin", filename="demo.bin")
    with Fetcher(tmp_path / "cache", client=httpx.Client(transport=httpx.MockTransport(ok))) as fetcher:
        cached = fetcher.fetch(spec)
    with Fetcher(
        tmp_path / "cache",
        revalidate=True,
        client=httpx.Client(transport=httpx.MockTransport(truncated)),
    ) as fetcher:
        result = fetcher.fetch(spec)

    assert result.record.sha256 == cached.record.sha256
    assert result.path.read_bytes() == b"A" * 20


def test_fetcher_revalidate_keeps_cache_on_unsolicited_206(tmp_path: Path) -> None:
    """强制校验没有请求 Range，收到 206 时不能把片段当成完整新版本。"""

    def ok(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"A" * 20, headers={"content-length": "20", "etag": '"e1"'})

    def partial(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            206,
            content=b"A" * 10,
            headers={"content-length": "10", "etag": '"e2"', "content-range": "bytes 0-9/20"},
        )

    spec = SourceSpec(name="demo", url="https://example.com/demo.bin", filename="demo.bin")
    with Fetcher(tmp_path / "cache", client=httpx.Client(transport=httpx.MockTransport(ok))) as fetcher:
        cached = fetcher.fetch(spec)
    with Fetcher(
        tmp_path / "cache",
        revalidate=True,
        client=httpx.Client(transport=httpx.MockTransport(partial)),
    ) as fetcher:
        result = fetcher.fetch(spec)

    assert result.record.sha256 == cached.record.sha256
    assert result.path.read_bytes() == b"A" * 20


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


def test_fetcher_does_not_mix_versions_on_resume(tmp_path: Path) -> None:
    """分片来自旧版本时，续传必须先校验校验值，否则会拼出两个版本的混合文件。"""
    v1, v2 = b"A" * 10, b"B" * 20
    state = {"phase": 1}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["phase"] == 1:
            state["phase"] = 2
            # 声明 20 字节但只发 10 字节：制造一个残留分片
            return httpx.Response(200, content=v1, headers={"content-length": str(len(v2)), "etag": '"v1"'})
        if request.headers.get("range") is not None:
            state["phase"] = 3
            # 上游已换成 v2，但服务端照旧返回 206
            return httpx.Response(
                206,
                content=v2[10:],
                headers={
                    "content-length": str(len(v2) - 10),
                    "etag": '"v2"',
                    "content-range": "bytes 10-19/20",
                },
            )
        return httpx.Response(200, content=v2, headers={"content-length": str(len(v2)), "etag": '"v2"'})

    spec = SourceSpec(name="demo", url="https://example.com/demo.bin", filename="demo.bin")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with Fetcher(tmp_path / "cache", retries=1, client=client) as fetcher, pytest.raises(SourceError):
        fetcher.fetch(spec)
    part = tmp_path / "cache" / "demo.bin.part"
    assert part.stat().st_size == 10

    with Fetcher(tmp_path / "cache", retries=1, client=client) as fetcher, pytest.raises(SourceError) as excinfo:
        fetcher.fetch(spec)
    assert "校验值不匹配" in str(excinfo.value)
    assert not part.exists(), "校验值不匹配时必须丢弃旧分片"

    with Fetcher(tmp_path / "cache", retries=1, client=client) as fetcher:
        result = fetcher.fetch(spec)
    assert result.path.read_bytes() == v2
    assert result.record.size_bytes == len(v2)


def test_fetcher_resumes_when_validator_matches(tmp_path: Path) -> None:
    """校验值一致时应继续断点续传，并带上 If-Range（避免因噎废食禁用续传）。"""
    total = b"A" * 20
    seen: list[tuple[str | None, str | None]] = []
    state = {"phase": 1}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers.get("range"), request.headers.get("if-range")))
        if state["phase"] == 1:
            state["phase"] = 2
            return httpx.Response(200, content=total[:10], headers={"content-length": "20", "etag": '"v1"'})
        return httpx.Response(
            206,
            content=total[10:],
            headers={"content-length": "10", "etag": '"v1"', "content-range": "bytes 10-19/20"},
        )

    spec = SourceSpec(name="demo", url="https://example.com/demo.bin", filename="demo.bin")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with Fetcher(tmp_path / "cache", retries=1, client=client) as fetcher, pytest.raises(SourceError):
        fetcher.fetch(spec)
    with Fetcher(tmp_path / "cache", retries=1, client=client) as fetcher:
        result = fetcher.fetch(spec)

    assert seen[-1] == ("bytes=10-", '"v1"')
    assert result.path.read_bytes() == total
    assert result.record.size_bytes == len(total)


def test_fetcher_recovers_from_stale_complete_part(tmp_path: Path) -> None:
    """残留完整分片触发 416 时，应丢弃 Range 并重新完整下载。"""
    payload = b"A" * 20
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("range"))
        if request.headers.get("range") is not None:
            return httpx.Response(416, headers={"content-range": f"bytes */{len(payload)}"})
        return httpx.Response(200, content=payload, headers={"etag": '"e2"'})

    cache = tmp_path / "cache"
    cache.mkdir()
    part = cache / "demo.bin.part"
    part.write_bytes(payload)
    (cache / "demo.bin.part.meta").write_text(
        json.dumps({"url": "https://example.com/demo.bin", "etag": '"e1"', "lastModified": ""}),
        encoding="utf-8",
    )

    spec = SourceSpec(name="demo", url="https://example.com/demo.bin", filename="demo.bin")
    with Fetcher(
        cache,
        retries=1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as fetcher:
        result = fetcher.fetch(spec)

    assert calls == ["bytes=20-", None]
    assert result.path.read_bytes() == payload
    assert not part.exists()


def test_fetcher_rejects_unsolicited_206(tmp_path: Path) -> None:
    """没请求 Range 却收到 206，说明这是片段，绝不能当成完整内容保存。"""
    total = b"A" * 40

    def handler(_request: httpx.Request) -> httpx.Response:
        # 只返回后半段，但用 206 伪装
        return httpx.Response(
            206,
            content=total[10:],
            headers={"content-length": "30", "etag": '"v1"', "content-range": "bytes 10-39/40"},
        )

    spec = SourceSpec(name="demo", url="https://example.com/demo.bin", filename="demo.bin")
    with (
        Fetcher(
            tmp_path / "cache",
            retries=1,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        ) as fetcher,
        pytest.raises(SourceError) as excinfo,
    ):
        fetcher.fetch(spec)
    assert "未请求断点续传却收到 206" in str(excinfo.value)
    assert not (tmp_path / "cache" / "demo.bin").exists()


def test_fetcher_rejects_mismatched_content_range(tmp_path: Path) -> None:
    """206 的 Content-Range 起点必须与本地分片对齐，否则会拼错数据。"""
    state = {"phase": 1}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["phase"] == 1:
            state["phase"] = 2
            return httpx.Response(200, content=b"A" * 10, headers={"content-length": "40", "etag": '"v1"'})
        assert request.headers.get("range") == "bytes=10-"
        # 起点写错（0 而不是 10）
        return httpx.Response(
            206,
            content=b"B" * 30,
            headers={"content-length": "30", "etag": '"v1"', "content-range": "bytes 0-29/40"},
        )

    spec = SourceSpec(name="demo", url="https://example.com/demo.bin", filename="demo.bin")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with Fetcher(tmp_path / "cache", retries=1, client=client) as fetcher, pytest.raises(SourceError):
        fetcher.fetch(spec)
    with Fetcher(tmp_path / "cache", retries=1, client=client) as fetcher, pytest.raises(SourceError) as excinfo:
        fetcher.fetch(spec)
    assert "Content-Range 起点" in str(excinfo.value)
    assert not (tmp_path / "cache" / "demo.bin.part").exists(), "起点不符时必须丢弃分片"


def test_fetcher_rejects_206_without_content_range_and_redownloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """206 缺少 Content-Range 时不能拼接；正常服务端应能随后完整重下。"""
    monkeypatch.setattr("immich_cn.fetching.time.sleep", lambda _seconds: None)
    payload = b"A" * 20
    calls: list[str | None] = []
    cache = tmp_path / "cache"
    cache.mkdir()
    part = cache / "demo.bin.part"
    part.write_bytes(payload[:10])
    (cache / "demo.bin.part.meta").write_text(
        json.dumps({"url": "https://example.com/demo.bin", "etag": '"v1"', "lastModified": ""}),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("range"))
        if request.headers.get("range") is not None:
            return httpx.Response(206, content=payload[10:], headers={"content-length": "10", "etag": '"v1"'})
        return httpx.Response(200, content=payload, headers={"content-length": "20", "etag": '"v1"'})

    spec = SourceSpec(name="demo", url="https://example.com/demo.bin", filename="demo.bin")
    with Fetcher(
        cache,
        retries=2,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as fetcher:
        result = fetcher.fetch(spec)

    assert calls == ["bytes=10-", None]
    assert result.path.read_bytes() == payload


def test_fetcher_rejects_partial_content_range_and_redownloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """206 只返回中间片段而不是完整尾部时，必须丢弃并完整重下。"""
    monkeypatch.setattr("immich_cn.fetching.time.sleep", lambda _seconds: None)
    payload = b"A" * 20
    calls: list[str | None] = []
    cache = tmp_path / "cache"
    cache.mkdir()
    part = cache / "demo.bin.part"
    part.write_bytes(payload[:10])
    (cache / "demo.bin.part.meta").write_text(
        json.dumps({"url": "https://example.com/demo.bin", "etag": '"v1"', "lastModified": ""}),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("range"))
        if request.headers.get("range") is not None:
            return httpx.Response(
                206,
                content=b"B" * 5,
                headers={
                    "content-length": "5",
                    "etag": '"v1"',
                    "content-range": "bytes 10-14/20",
                },
            )
        return httpx.Response(200, content=payload, headers={"content-length": "20", "etag": '"v1"'})

    spec = SourceSpec(name="demo", url="https://example.com/demo.bin", filename="demo.bin")
    with Fetcher(
        cache,
        retries=2,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as fetcher:
        result = fetcher.fetch(spec)

    assert calls == ["bytes=10-", None]
    assert result.path.read_bytes() == payload


def test_fetcher_accepts_correct_content_range(tmp_path: Path) -> None:
    """Content-Range 与分片对齐时正常续传（防止因噎废食）。"""
    total = b"A" * 20
    state = {"phase": 1}

    def handler(_request: httpx.Request) -> httpx.Response:
        if state["phase"] == 1:
            state["phase"] = 2
            return httpx.Response(200, content=total[:10], headers={"content-length": "20", "etag": '"v1"'})
        return httpx.Response(
            206,
            content=total[10:],
            headers={"content-length": "10", "etag": '"v1"', "content-range": "bytes 10-19/20"},
        )

    spec = SourceSpec(name="demo", url="https://example.com/demo.bin", filename="demo.bin")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with Fetcher(tmp_path / "cache", retries=1, client=client) as fetcher, pytest.raises(SourceError):
        fetcher.fetch(spec)
    with Fetcher(tmp_path / "cache", retries=1, client=client) as fetcher:
        result = fetcher.fetch(spec)
    assert result.path.read_bytes() == total


def test_fetcher_does_not_retry_permanent_client_errors(tmp_path: Path) -> None:
    """404 这类永久错误只应请求一次，避免无谓重试与放大上游压力。"""
    calls: list[int] = []

    def not_found(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404, content=b"nope")

    spec = SourceSpec(name="missing", url="https://example.com/missing.txt", filename="missing.txt")
    with (
        Fetcher(
            tmp_path / "cache",
            retries=4,
            client=httpx.Client(transport=httpx.MockTransport(not_found)),
        ) as fetcher,
        pytest.raises(SourceError),
    ):
        fetcher.fetch(spec)
    assert len(calls) == 1


def test_fetcher_retries_retryable_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """503 属于可重试状态，应当重试到上限。"""
    monkeypatch.setattr("immich_cn.fetching.time.sleep", lambda _seconds: None)
    calls: list[int] = []

    def unavailable(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, content=b"later")

    spec = SourceSpec(name="busy", url="https://example.com/busy.txt", filename="busy.txt")
    with (
        Fetcher(
            tmp_path / "cache",
            retries=3,
            client=httpx.Client(transport=httpx.MockTransport(unavailable)),
        ) as fetcher,
        pytest.raises(SourceError),
    ):
        fetcher.fetch(spec)
    assert len(calls) == 3


def test_retry_delay_prefers_retry_after_header() -> None:
    request = httpx.Request("GET", "https://example.com/x")
    seconds = httpx.HTTPStatusError(
        "429",
        request=request,
        response=httpx.Response(429, headers={"retry-after": "7"}, request=request),
    )
    assert retry_delay(1, seconds) == 7.0

    http_date = httpx.HTTPStatusError(
        "429",
        request=request,
        response=httpx.Response(
            429,
            headers={"retry-after": "Wed, 21 Oct 2099 07:28:00 GMT"},
            request=request,
        ),
    )
    assert retry_delay(1, http_date) == 120.0


def test_retry_delay_falls_back_to_exponential_backoff() -> None:
    assert retry_delay(1, httpx.ConnectError("boom")) == 2.0
    assert retry_delay(5, httpx.ConnectError("boom")) == 30.0


@requires_real_permissions
def test_fetcher_reports_readonly_cache_dir_as_source_error(tmp_path: Path) -> None:
    """缓存目录不可写时必须抛出 ImmichCnError 子类，而不是裸 OSError。"""
    cache = tmp_path / "cache"
    cache.mkdir()
    cache.chmod(0o555)
    try:
        with pytest.raises(SourceError) as excinfo:
            Fetcher(cache)
    finally:
        cache.chmod(0o755)
    assert "无法创建缓存目录" in str(excinfo.value)


def test_fetcher_rejects_content_not_matching_pinned_digest(tmp_path: Path) -> None:
    """固定版本的数据源必须校验摘要，防止上游内容被替换（供应链）。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"tampered")

    spec = SourceSpec(
        name="pinned",
        url="https://example.com/pinned.tgz",
        filename="pinned.tgz",
        expected_sha256="0" * 64,
    )
    with (
        Fetcher(
            tmp_path / "cache",
            retries=1,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        ) as fetcher,
        pytest.raises(SourceError) as excinfo,
    ):
        fetcher.fetch(spec)
    assert "摘要与预期不符" in str(excinfo.value)
    assert not (tmp_path / "cache" / "pinned.tgz").exists(), "校验失败的内容不得进入缓存"


def test_fetcher_accepts_content_matching_pinned_digest(tmp_path: Path) -> None:
    payload = b"trusted"
    digest = sha256_bytes(payload)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    spec = SourceSpec(
        name="pinned",
        url="https://example.com/pinned.tgz",
        filename="pinned.tgz",
        expected_sha256=digest,
    )
    with Fetcher(
        tmp_path / "cache",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as fetcher:
        result = fetcher.fetch(spec)
    assert result.record.sha256 == digest


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
