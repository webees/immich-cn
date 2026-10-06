"""带缓存、重试与完整性校验的下载工具。"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from immich_cn.config import USER_AGENT, SourceSpec
from immich_cn.errors import SourceError
from immich_cn.logging_setup import get_logger
from immich_cn.models import SourceRecord

logger = get_logger("http")

_CHUNK = 1024 * 1024
#: 只有这些状态码才值得重试；其余 4xx 视为永久失败，立即放弃（避免无谓重试与放大限流）。
_RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
_MAX_RETRY_DELAY = 120.0


class _RangeNotSatisfiableError(SourceError):
    """本地分片使 Range 越界，需要改为完整下载。"""


def _retry_delay(attempt: int, error: Exception) -> float:
    """计算退避时间：优先遵循上游的 ``Retry-After``，否则指数退避。"""
    response = getattr(error, "response", None)
    if isinstance(response, httpx.Response):
        hint = _retry_after_seconds(response)
        if hint is not None:
            return hint
    return float(min(2**attempt, 30))


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    value = raw.strip()
    if value.isdigit():
        return min(float(value), _MAX_RETRY_DELAY)
    try:
        when = parsedate_to_datetime(value)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        delta = (when - datetime.now(UTC)).total_seconds()
    except (TypeError, ValueError, AttributeError):
        return None
    return max(0.0, min(delta, _MAX_RETRY_DELAY))


def _part_meta_path(part: Path) -> Path:
    return part.parent / f"{part.name}.meta"


def _content_range_start(value: str) -> int | None:
    """从 ``Content-Range: bytes 10-39/40`` 解析起始偏移。"""
    match = re.match(r"\s*bytes\s+(\d+)-", value)
    return int(match.group(1)) if match else None


def _load_part_meta(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): str(v) for k, v in payload.items()} if isinstance(payload, dict) else {}


def _write_part_meta(part: Path, spec: SourceSpec, etag: str | None, last_modified: str | None) -> None:
    """记录分片对应的上游校验值，避免把不同版本的字节拼在一起。"""
    _part_meta_path(part).write_text(
        json.dumps({"url": spec.url, "etag": etag or "", "lastModified": last_modified or ""}) + "\n",
        encoding="utf-8",
    )


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
        try:
            self._meta_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise SourceError(f"无法创建缓存目录 {self._meta_dir}：{error}") from error
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
        if not isinstance(payload.get("sha256"), str) or not payload["sha256"]:
            return None
        size_bytes = payload.get("sizeBytes")
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
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
                if spec.expected_sha256 and (
                    record.sha256 != spec.expected_sha256 or sha256_file(target) != spec.expected_sha256
                ):
                    # 固定版本的缓存必须与预期摘要一致，否则重新下载
                    logger.warning("缓存 %s 与预期摘要不符，重新下载", spec.name)
                    target.unlink(missing_ok=True)
                    self._meta_path(spec).unlink(missing_ok=True)
                    return self._download(spec, target)
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

        _verify_expected_digest(spec, digest.hexdigest())
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
        expected_etag = ""
        if part.exists() and part.stat().st_size > 0:
            meta = _load_part_meta(_part_meta_path(part))
            if meta.get("url") == spec.url:
                expected_etag = meta.get("etag", "")
                headers["Range"] = f"bytes={part.stat().st_size}-"
                if expected_etag:
                    # If-Range：校验值变化时服务端会改发完整正文，从协议层避免拼接
                    headers["If-Range"] = expected_etag
            else:
                logger.debug("分片缺少可信校验信息，改为完整重下 %s", spec.name)
                part.unlink(missing_ok=True)
                _part_meta_path(part).unlink(missing_ok=True)

        last_error: Exception | None = None
        attempt = 1
        while attempt <= self._retries:
            try:
                return self._stream_to_file(spec, target, part, headers, expected_etag=expected_etag)
            except _RangeNotSatisfiableError:
                logger.warning("分片 %s 的 Range 已越界，丢弃后完整重下", spec.name)
                part.unlink(missing_ok=True)
                _part_meta_path(part).unlink(missing_ok=True)
                headers.pop("Range", None)
                headers.pop("If-Range", None)
                expected_etag = ""
                continue
            except (httpx.HTTPError, SourceError) as error:
                last_error = error
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in _RETRY_STATUS:
                    logger.warning(
                        "下载 %s 失败且不可重试：HTTP %s",
                        spec.name,
                        error.response.status_code,
                    )
                    break
                if attempt == self._retries:
                    break
                delay = _retry_delay(attempt, error)
                logger.warning("下载 %s 失败（第 %d 次）：%s；%.0fs 后重试", spec.name, attempt, error, delay)
                time.sleep(delay)
                attempt += 1
            except OSError as error:
                # 本地 I/O 故障（权限、磁盘满、路径不存在）重试无益，直接给出可读错误
                raise SourceError(f"写入缓存失败（{spec.name}）：{error}") from error
        raise SourceError(f"下载 {spec.url} 失败：{last_error}") from last_error

    def _stream_to_file(
        self,
        spec: SourceSpec,
        target: Path,
        part: Path,
        headers: dict[str, str],
        *,
        expected_etag: str = "",
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
                if resume_from:
                    raise _RangeNotSatisfiableError(f"{spec.name} 的本地分片已使 Range 越界")
                response.raise_for_status()
            response.raise_for_status()
            if resume_from and response.status_code != 206:
                logger.debug("服务端不支持断点续传，重新下载 %s", spec.name)
                resume_from = 0
                digest = hashlib.sha256()

            response_etag = response.headers.get("etag")
            response_last_modified = response.headers.get("last-modified")
            if response.status_code == 206:
                # 206 只能出现在"我们主动请求了 Range"的前提下，
                # 否则它可能是服务端/缓存返回的片段，直接保存会得到截断文件。
                if not resume_from:
                    raise SourceError(f"{spec.name} 未请求断点续传却收到 206 响应，拒绝作为完整内容保存")
                start = _content_range_start(response.headers.get("content-range", ""))
                if start is not None and start != resume_from:
                    part.unlink(missing_ok=True)
                    _part_meta_path(part).unlink(missing_ok=True)
                    raise SourceError(
                        f"{spec.name} 的 Content-Range 起点 {start} 与本地分片 {resume_from} 不符，"
                        "已丢弃分片改为完整重下"
                    )
            if resume_from and response.status_code == 206:
                # 206 的校验值必须与本地分片一致，否则会拼出两个版本的混合文件
                if not expected_etag or response_etag != expected_etag:
                    part.unlink(missing_ok=True)
                    _part_meta_path(part).unlink(missing_ok=True)
                    raise SourceError(
                        f"{spec.name} 断点续传校验值不匹配（本地 {expected_etag or '未知'} / "
                        f"上游 {response_etag or '未知'}），已丢弃分片改为完整重下"
                    )
            elif not resume_from:
                _write_part_meta(part, spec, response_etag, response_last_modified)

            mode = "ab" if resume_from else "wb"
            with part.open(mode) as handle:
                for chunk in response.iter_bytes(_CHUNK):
                    digest.update(chunk)
                    handle.write(chunk)
            etag = response_etag
            last_modified = response_last_modified
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

        _verify_expected_digest(spec, digest.hexdigest())
        part.replace(target)
        _part_meta_path(part).unlink(missing_ok=True)
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


def _verify_expected_digest(spec: SourceSpec, digest: str) -> None:
    """固定版本的数据源必须与预期摘要一致，防止上游内容被替换。"""
    if spec.expected_sha256 and digest != spec.expected_sha256:
        raise SourceError(f"{spec.name} 内容摘要与预期不符（期望 {spec.expected_sha256[:12]}…，实际 {digest[:12]}…）")


def _as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0
