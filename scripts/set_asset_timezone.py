"""把 Immich asset 的 EXIF timeZone 批量设置为指定 IANA timezone。

Immich 的照片详情页优先显示 ``dateTimeOriginal + exifInfo.timeZone``。
本工具只调用 Immich 官方 API 更新 metadata，不修改原图文件；默认 dry-run。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Iterator, Sequence
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

DEFAULT_TIMEZONE = "Asia/Shanghai"
SEARCH_PAGE_SIZE = 1000
RETRY_STATUS = {408, 425, 429}


def _client(base_url: str, api_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        headers={"x-api-key": api_key, "accept": "application/json"},
        timeout=30.0,
    )


def _request(client: httpx.Client, method: str, url: str, **kwargs: Any) -> httpx.Response:
    for attempt in range(1, 4):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TransportError as error:
            if attempt == 3:
                raise RuntimeError(f"Immich API request failed after {attempt} attempts: {url}: {error}") from error
            time.sleep(2**attempt)
            continue
        if response.status_code not in RETRY_STATUS and response.status_code < 500:
            return response
        if attempt == 3:
            return response
        time.sleep(2**attempt)
    raise RuntimeError(f"Immich API request failed: {url}")  # pragma: no cover


def _request_json(client: httpx.Client, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    response = _request(client, method, url, **kwargs)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeError(f"Immich API returned invalid JSON: {url}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Immich API returned non-object JSON: {url}")
    return payload


def iter_assets(client: httpx.Client) -> Iterator[dict[str, Any]]:
    """分页读取所有非删除 asset。"""
    page = 1
    seen = 0
    while True:
        payload = _request_json(
            client,
            "POST",
            "/api/search/metadata",
            json={"page": page, "size": SEARCH_PAGE_SIZE, "withExif": True},
        )
        block = payload.get("assets")
        if not isinstance(block, dict):
            raise RuntimeError("Immich search response 缺少 assets 对象")
        items = block.get("items")
        if not isinstance(items, list):
            raise RuntimeError("Immich search response 缺少 assets.items")
        for item in items:
            if isinstance(item, dict):
                seen += 1
                yield item
        total = block.get("total")
        if not items:
            return
        if isinstance(total, int) and seen >= total:
            return
        if not isinstance(total, int) and len(items) < SEARCH_PAGE_SIZE:
            return
        page += 1


def select_asset_ids(assets: Iterator[dict[str, Any]], timezone: str) -> tuple[int, list[str]]:
    """返回 (扫描数量, 需要更新的 asset ID)。"""
    scanned = 0
    ids: list[str] = []
    for asset in assets:
        scanned += 1
        exif = asset.get("exifInfo")
        if not isinstance(exif, dict):
            continue
        if not exif.get("dateTimeOriginal"):
            continue
        if exif.get("timeZone") == timezone:
            continue
        asset_id = asset.get("id")
        if isinstance(asset_id, str) and asset_id:
            ids.append(asset_id)
    return scanned, ids


def apply_timezone(
    client: httpx.Client,
    ids: Sequence[str],
    timezone: str,
    *,
    batch_size: int = 500,
) -> int:
    """通过官方 bulk update API 设置 timeZone，返回更新的 asset 数量。"""
    updated = 0
    for start in range(0, len(ids), batch_size):
        batch = list(ids[start : start + batch_size])
        # Immich v3.3.0 起推荐 PATCH；v1.136.0 等旧版本只有 PUT。
        response = _request(
            client,
            "PATCH",
            "/api/assets",
            json={"ids": batch, "timeZone": timezone},
        )
        if response.status_code in {404, 405}:
            response = _request(
                client,
                "PUT",
                "/api/assets",
                json={"ids": batch, "timeZone": timezone},
            )
        response.raise_for_status()
        updated += len(batch)
    return updated


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("IMMICH_BASE_URL", "http://localhost:2283"))
    parser.add_argument("--api-key", default=os.environ.get("IMMICH_API_KEY"))
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--apply", action="store_true", help="真正写入；默认只 dry-run")
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.api_key:
        print("缺少 API key：使用 --api-key 或 IMMICH_API_KEY", file=sys.stderr)
        return 2
    if args.batch_size < 1:
        print("--batch-size 必须大于 0", file=sys.stderr)
        return 2
    try:
        ZoneInfo(args.timezone)
    except ZoneInfoNotFoundError:
        print(f"未知 IANA timezone：{args.timezone}", file=sys.stderr)
        return 2

    with _client(args.base_url, args.api_key) as client:
        scanned, ids = select_asset_ids(iter_assets(client), args.timezone)
        print(f"扫描 asset：{scanned}，需要设置 timeZone={args.timezone}：{len(ids)}")
        if not args.apply:
            print("dry-run：未写入；确认后加 --apply")
            return 0
        updated = apply_timezone(client, ids, args.timezone, batch_size=args.batch_size)
        print(f"已更新 asset：{updated}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
