"""带缓存、重试与完整性校验的下载工具。"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from immich_cn.config import USER_AGENT, SourceSpec
from immich_cn.errors import SourceError
from immich_cn.logging_setup import get_logger
from immich_cn.models import SourceRecord

logger = get_logger("http")

_CHUNK = 1024 * 1024
_RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class FetchedSource:
    """下载完成的源文件及其指纹。"""

    spec: SourceSpec
    path: Path
    record: SourceRecord


class Fetcher:
    """下载器：磁盘缓存 + 指数退避重试 + SHA256 指纹。"""

    def __init__(
        self,
        cache_dir: Path,
        *,
        force: bool = False,
        revalidate: bool = False,
        timeout: float = 60.0,
        retries: int = 4,
        client: httpx.Client | None = None,
    ) -> None:
        self._cache_dir = cache_dir
        self._force = force
        self._revalidate = revalidate
        self._retries = retries
        self._meta_dir = cache_dir / ".meta"
        self._meta_dir.mkdir(parents=True, exist_ok=True)
        self._owns_client = client is None
        self._client = client or httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout, connect=20.0),
            headers={"User-Agent": USER_AGENT},
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _meta_path(self, spec: SourceSpec) -> Path:
        return self._meta_dir / f"{spec.name}.json"

    def _load_meta(self, spec: SourceSpec) -> dict[str, object] | None:
        meta_path = self._meta_path(spec)
        if not meta_path.exists():
            return None
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("url") != spec.url:
            return None
        return payload

    def fetch(self, spec: SourceSpec) -> FetchedSource:
        """确保 ``spec`` 已缓存到本地，返回路径与指纹。"""
        target = self._cache_dir / spec.cache_filename
        meta = self._load_meta(spec)

        if target.exists() and meta and not self._force:
            record = SourceRecord(
                name=spec.name,
                url=spec.url,
                sha256=str(meta["sha256"]),
                size_bytes=_as_int(meta.get("sizeBytes")),
                etag=_opt_str(meta.get("etag")),
                last_modified=_opt_str(meta.get("lastModified")),
            )
            if target.stat().st_size == record.size_bytes:
                if self._revalidate and (record.etag or record.last_modified):
                    return self._revalidate_cached(spec, target, record)
                logger.debug("命中缓存 %s (%s)", spec.name, record.sha256[:12])
                return FetchedSource(spec=spec, path=target, record=record)
            logger.warning("缓存文件 %s 大小不符，重新下载", target)

        return self._download(spec, target)

    def _revalidate_cached(self, spec: SourceSpec, target: Path, cached: SourceRecord) -> FetchedSource:
        """用 If-None-Match / If-Modified-Since 校验上游是否变化。

        GeoNames 等数据源支持强 ETag：未更新时返回 304 且不传输正文，
        因此每日自动更新几乎不消耗带宽；一旦上游更新则立即重新下载。
        """
        headers: dict[str, str] = {}
        if cached.etag:
            headers["If-None-Match"] = cached.etag
        if cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified

        part = target.with_suffix(target.suffix + ".part")
        try:
            with self._client.stream("GET", spec.url, headers=headers) as response:
                if response.status_code == 304:
                    logger.info("上游未更新 %s", spec.name)
                    self._write_meta(spec, cached)
                    return FetchedSource(spec=spec, path=target, record=cached)
                response.raise_for_status()
                digest = hashlib.sha256()
                with part.open("wb") as handle:
                    for chunk in response.iter_bytes(_CHUNK):
                        digest.update(chunk)
                        handle.write(chunk)
                etag = response.headers.get("etag")
                last_modified = response.headers.get("last-modified")
        except (httpx.HTTPError, OSError, SourceError) as error:
            logger.warning("校验 %s 失败，继续使用本地缓存：%s", spec.name, error)
            return FetchedSource(spec=spec, path=target, record=cached)

        if part.stat().st_size == 0 and target.stat().st_size > 0:
            # 空正文通常意味着上游异常，绝不能覆盖已有的健康缓存。
            part.unlink(missing_ok=True)
            logger.warning("校验 %s 返回空内容，保留本地缓存", spec.name)
            return FetchedSource(spec=spec, path=target, record=cached)

        part.replace(target)
        record = SourceRecord(
            name=spec.name,
            url=spec.url,
            sha256=digest.hexdigest(),
            size_bytes=target.stat().st_size,
            etag=etag,
            last_modified=last_modified,
        )
        self._write_meta(spec, record)
        logger.info("上游已更新 %s（%.1f MiB）", spec.name, record.size_bytes / 1048576)
        return FetchedSource(spec=spec, path=target, record=record)

    def _download(self, spec: SourceSpec, target: Path) -> FetchedSource:
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(target.suffix + ".part")
        headers: dict[str, str] = {}
        if part.exists() and part.stat().st_size > 0:
            headers["Range"] = f"bytes={part.stat().st_size}-"

        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                return self._stream_to_file(spec, target, part, headers)
            except (httpx.HTTPError, SourceError) as error:
                last_error = error
                if attempt == self._retries:
                    break
                delay = min(2**attempt, 30)
                logger.warning("下载 %s 失败（第 %d 次）：%s；%.0fs 后重试", spec.name, attempt, error, delay)
                time.sleep(delay)
        raise SourceError(f"下载 {spec.url} 失败：{last_error}") from last_error

    def _stream_to_file(
        self,
        spec: SourceSpec,
        target: Path,
        part: Path,
        headers: dict[str, str],
    ) -> FetchedSource:
        logger.info("下载 %s", spec.url)
        digest = hashlib.sha256()
        resume_from = 0
        if headers.get("Range"):
            resume_from = part.stat().st_size
            with part.open("rb") as existing:
                for chunk in iter(lambda: existing.read(_CHUNK), b""):
                    digest.update(chunk)

        with self._client.stream("GET", spec.url, headers=headers) as response:
            if response.status_code == 416:
                # Range 越界说明本地已有完整文件，直接校验。
                response.raise_for_status()
            response.raise_for_status()
            if resume_from and response.status_code != 206:
                logger.debug("服务端不支持断点续传，重新下载 %s", spec.name)
                resume_from = 0
                digest = hashlib.sha256()
            mode = "ab" if resume_from else "wb"
            with part.open(mode) as handle:
                for chunk in response.iter_bytes(_CHUNK):
                    digest.update(chunk)
                    handle.write(chunk)
            etag = response.headers.get("etag")
            last_modified = response.headers.get("last-modified")
            expected_raw = response.headers.get("content-length")
            encoding = (response.headers.get("content-encoding") or "identity").lower()
            status_code = response.status_code

        # 校验实际写入的字节数，避免把被截断的响应当成成功结果缓存下来。
        # 服务端启用了内容编码时 iter_bytes 返回的是解码后数据，长度不可比，直接跳过。
        if encoding == "identity" and expected_raw and expected_raw.isdigit():
            expected = int(expected_raw) + (resume_from if status_code == 206 else 0)
            actual = part.stat().st_size
            if actual != expected:
                raise SourceError(f"{spec.name} 下载不完整：收到 {actual} 字节，预期 {expected} 字节")

        part.replace(target)
        record = SourceRecord(
            name=spec.name,
            url=spec.url,
            sha256=digest.hexdigest(),
            size_bytes=target.stat().st_size,
            etag=etag,
            last_modified=last_modified,
        )
        self._write_meta(spec, record)
        logger.info("完成 %s（%.1f MiB）", spec.name, record.size_bytes / 1048576)
        return FetchedSource(spec=spec, path=target, record=record)

    def _write_meta(self, spec: SourceSpec, record: SourceRecord) -> None:
        self._meta_path(spec).write_text(
            json.dumps(record.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0
