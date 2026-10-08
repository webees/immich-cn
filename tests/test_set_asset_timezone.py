from __future__ import annotations

import json

import httpx
from scripts.set_asset_timezone import SEARCH_PAGE_SIZE, apply_timezone, iter_assets, select_asset_ids


def test_select_asset_ids_skips_missing_and_matching_timezone() -> None:
    assets = [
        {"id": "a", "exifInfo": {"dateTimeOriginal": "2026-01-01T00:00:00+00:00", "timeZone": "UTC"}},
        {"id": "b", "exifInfo": {"dateTimeOriginal": "2026-01-01T00:00:00+00:00", "timeZone": "Asia/Shanghai"}},
        {"id": "c", "exifInfo": {"timeZone": "UTC"}},
        {"id": "d"},
    ]
    scanned, ids = select_asset_ids(iter(assets), "Asia/Shanghai")
    assert scanned == 4
    assert ids == ["a"]


def test_iter_assets_reads_search_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/search/metadata"
        page = json.loads(request.content)["page"]
        if page == 1:
            return httpx.Response(200, json={"assets": {"items": [{"id": "a"}], "total": 2}})
        return httpx.Response(200, json={"assets": {"items": [{"id": "b"}], "total": 2}})

    with httpx.Client(base_url="http://immich", transport=httpx.MockTransport(handler)) as client:
        assert [asset["id"] for asset in iter_assets(client)] == ["a", "b"]


def test_iter_assets_pages_when_total_missing() -> None:
    """响应不带 total 时必须按「页面是否满」继续翻页，否则会静默丢掉第一页之后的 asset。"""
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = json.loads(request.content)["page"]
        pages.append(page)
        if page == 1:
            items = [{"id": f"a{index}"} for index in range(SEARCH_PAGE_SIZE)]
            return httpx.Response(200, json={"assets": {"items": items}})
        if page == 2:
            return httpx.Response(200, json={"assets": {"items": [{"id": "b"}]}})
        raise AssertionError("total 缺失时不应额外翻页")

    with httpx.Client(base_url="http://immich", transport=httpx.MockTransport(handler)) as client:
        assets = list(iter_assets(client))

    assert pages == [1, 2]
    assert len(assets) == SEARCH_PAGE_SIZE + 1
    assert assets[-1]["id"] == "b"


def test_apply_timezone_uses_bulk_update_api() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/api/assets"
        requests.append(json.loads(request.content))
        return httpx.Response(204)

    with httpx.Client(base_url="http://immich", transport=httpx.MockTransport(handler)) as client:
        updated = apply_timezone(client, ["a", "b", "c"], "Asia/Shanghai", batch_size=2)

    assert updated == 3
    assert requests == [
        {"ids": ["a", "b"], "timeZone": "Asia/Shanghai"},
        {"ids": ["c"], "timeZone": "Asia/Shanghai"},
    ]


def test_apply_timezone_falls_back_to_put_for_old_immich() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PATCH":
            return httpx.Response(405)
        return httpx.Response(204)

    with httpx.Client(base_url="http://immich", transport=httpx.MockTransport(handler)) as client:
        updated = apply_timezone(client, ["a"], "Asia/Shanghai")

    assert updated == 1
    assert methods == ["PATCH", "PUT"]
