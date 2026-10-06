from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest

from immich_cn.logging_setup import get_logger
from immich_cn.models import Place, PlaceNames
from immich_cn.providers.amap import AMAP_ENDPOINT, AmapEnricher, AmapOptions, _parse_regeocode
from immich_cn.providers.geo import out_of_china, wgs84_to_gcj02
from immich_cn.providers.nominatim import NOMINATIM_ENDPOINT, NominatimEnricher, NominatimOptions, _parse
from tests.synthetic import geo_row


def make_place(*, latitude: str = "31.30408", longitude: str = "120.59538", country: str = "CN") -> Place:
    place = Place.from_line(
        geo_row(1, "Suzhou", latitude=latitude, longitude=longitude, country=country, admin1="04", admin2="SZ")
    )
    assert place is not None
    return place


# ---- 坐标转换 -------------------------------------------------------------


def test_out_of_china() -> None:
    assert out_of_china(-74.00597, 40.71427)
    assert not out_of_china(116.39723, 39.9075)


def test_wgs84_to_gcj02_is_noop_outside_china() -> None:
    assert wgs84_to_gcj02(-74.00597, 40.71427) == (-74.00597, 40.71427)


def test_wgs84_to_gcj02_applies_expected_offset_in_china() -> None:
    longitude, latitude = wgs84_to_gcj02(116.39723, 39.9075)
    # 北京地区 GCJ-02 偏移量约 500 米量级
    assert 0.002 < longitude - 116.39723 < 0.008
    assert 0.0005 < latitude - 39.9075 < 0.005


# ---- 高德 -----------------------------------------------------------------


def test_parse_regeocode_falls_back_to_parent_levels() -> None:
    parsed = _parse_regeocode(
        {
            "addressComponent": {
                "country": "中国",
                "province": "北京市",
                "city": [],
                "district": "朝阳区",
                "township": "三里屯街道",
            }
        }
    )
    assert parsed is not None
    assert parsed["admin_1"] == "北京市"
    assert parsed["admin_2"] == "北京市"
    assert parsed["admin_3"] == "朝阳区"
    assert parsed["admin_4"] == "三里屯街道"


def test_parse_regeocode_returns_none_without_levels() -> None:
    assert _parse_regeocode({"addressComponent": {"country": "中国"}}) is None
    assert _parse_regeocode(None) is None


def test_amap_enricher_prefetch_and_enrich(tmp_path: Path) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "restapi.amap.com"
        requested.append(str(request.url.params.get("location")))
        return httpx.Response(
            200,
            json={
                "status": "1",
                "regeocodes": [
                    {
                        "addressComponent": {
                            "country": "中国",
                            "province": "江苏省",
                            "city": "苏州市",
                            "district": "昆山市",
                            "township": "周市镇",
                        }
                    }
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    enricher = AmapEnricher(AmapOptions(api_key="test"), tmp_path / "amap.jsonl", client=client)
    place = make_place()
    enricher.prefetch([place])
    assert len(requested) == 1

    names = enricher.enrich(place, PlaceNames(geoname_id=1))
    assert names.admin_1 == "江苏省"
    assert names.admin_3 == "昆山市"
    assert names.admin_4 == "周市镇"

    # 第二次预取应命中缓存，不再发起请求
    enricher.prefetch([place])
    assert len(requested) == 1
    assert str(client.base_url) == str(httpx.URL(""))


def test_amap_enricher_skips_other_countries(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - 不应被调用
        raise AssertionError("不应发起请求")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    enricher = AmapEnricher(AmapOptions(api_key="test"), tmp_path / "amap.jsonl", client=client)
    names = enricher.enrich(make_place(country="US"), PlaceNames(geoname_id=1, admin_2="纽约"))
    assert names.admin_2 == "纽约"


# ---- Nominatim ------------------------------------------------------------


def test_parse_nominatim_orders_admin_levels() -> None:
    payload = {
        "features": [
            {
                "properties": {
                    "geocoding": {
                        "country": "日本",
                        "admin": {"level10": "札幌市", "level8": "石狩振興局", "level4": "北海道"},
                    }
                }
            }
        ]
    }
    parsed = _parse(payload)
    assert parsed["admin_1"] == "北海道"
    assert parsed["admin_2"] == "石狩振興局"
    assert parsed["admin_3"] == "札幌市"


def test_parse_nominatim_empty_payload() -> None:
    assert _parse({"features": []}) == {"_error": "empty"}
    assert _parse(None) == {"_error": "empty"}


def test_nominatim_enricher_uses_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "nominatim.openstreetmap.org"
        calls.append(request.url.params.get("lat", ""))
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "properties": {
                            "geocoding": {
                                "country": "日本",
                                "admin": {"level4": "北海道", "level8": "石狩振興局", "level10": "札幌市"},
                            }
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    enricher = NominatimEnricher(
        NominatimOptions(countries=("JP",)),
        tmp_path / "nominatim.jsonl",
        user_agent="immich-cn-test/1.0",
        client=client,
    )
    place = make_place(country="JP", latitude="43.06417", longitude="141.34694")
    enricher.prefetch([place])
    enricher.prefetch([place])
    assert len(calls) == 1

    names = enricher.enrich(place, PlaceNames(geoname_id=1))
    assert names.admin_1 == "北海道"
    assert names.admin_3 == "札幌市"


def test_provider_cache_is_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "cache.jsonl"
    from immich_cn.providers.cache import JsonlCache

    cache = JsonlCache(path)
    cache.put("1,2", {"admin_1": "江苏省"})
    assert json.loads(path.read_text(encoding="utf-8"))["value"]["admin_1"] == "江苏省"
    assert JsonlCache(path).get("1,2") == {"admin_1": "江苏省"}


def test_amap_endpoint_is_https() -> None:
    assert AMAP_ENDPOINT.startswith("https://")
    assert NOMINATIM_ENDPOINT.startswith("https://")


def test_amap_requires_api_key(tmp_path: Path) -> None:
    from immich_cn.errors import ConfigError

    with pytest.raises(ConfigError):
        AmapEnricher(AmapOptions(api_key=""), tmp_path / "x.jsonl")


def test_amap_does_not_log_api_key_on_failure(tmp_path: Path) -> None:
    """请求失败时 httpx 异常里带完整 URL（含 key=...），日志必须脱敏。"""
    secret = "super-secret-amap-key-1234567890"
    captured: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    logger = get_logger("amap")
    handler = Capture()
    logger.addHandler(handler)
    try:
        client = httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(403, content=b'{"status":"0"}'))
        )
        enricher = AmapEnricher(
            AmapOptions(api_key=secret, retries=1),
            tmp_path / "amap.jsonl",
            client=client,
        )
        enricher.prefetch([make_place()])
    finally:
        logger.removeHandler(handler)

    assert captured, "应至少记录一条失败日志"
    assert all(secret not in message for message in captured), captured
    assert any("***" in message for message in captured), captured


def test_amap_transient_failure_is_not_negatively_cached(tmp_path: Path) -> None:
    """一次 429 不能永久跳过该坐标：服务恢复后必须能拿到数据。"""
    cache = tmp_path / "amap.jsonl"
    place = make_place()

    failing = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(429, content=b"{}")))
    first = AmapEnricher(AmapOptions(api_key="k", retries=1), cache, client=failing)
    first.prefetch([place])

    healthy = httpx.Client(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                json={
                    "status": "1",
                    "regeocodes": [
                        {
                            "addressComponent": {
                                "country": "中国",
                                "province": "江苏省",
                                "city": "苏州市",
                                "district": "昆山市",
                                "township": "周市镇",
                            }
                        }
                    ],
                },
            )
        )
    )
    second = AmapEnricher(AmapOptions(api_key="k", retries=1), cache, client=healthy)
    second.prefetch([place])
    names = second.enrich(place, PlaceNames(geoname_id=1))

    assert names.admin_3 == "昆山市"
    assert names.admin_4 == "周市镇"


def test_amap_legacy_error_cache_entries_are_retried(tmp_path: Path) -> None:
    """历史缓存里残留的 _error 条目必须被当作失效，重新请求。"""
    cache = tmp_path / "amap.jsonl"
    cache.write_text('{"key": "120.59538,31.30408", "value": {"_error": "request-failed"}}\n', encoding="utf-8")
    place = make_place()

    healthy = httpx.Client(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                json={
                    "status": "1",
                    "regeocodes": [
                        {
                            "addressComponent": {
                                "country": "中国",
                                "province": "江苏省",
                                "city": "苏州市",
                                "district": "昆山市",
                            }
                        }
                    ],
                },
            )
        )
    )
    enricher = AmapEnricher(AmapOptions(api_key="k", retries=1), cache, client=healthy)
    enricher.prefetch([place])
    assert enricher.enrich(place, PlaceNames(geoname_id=1)).admin_3 == "昆山市"


def test_nominatim_transient_failure_is_not_negatively_cached(tmp_path: Path) -> None:
    """Nominatim 同样不能把瞬时故障写进负缓存。"""
    cache = tmp_path / "nominatim.jsonl"
    place = make_place(country="JP", latitude="43.06417", longitude="141.34694")

    failing = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(503, content=b"busy")))
    first = NominatimEnricher(NominatimOptions(countries=("JP",), retries=1), cache, client=failing)
    first.prefetch([place])

    healthy = httpx.Client(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                json={
                    "features": [
                        {
                            "properties": {
                                "geocoding": {
                                    "country": "日本",
                                    "admin": {"level4": "北海道", "level8": "石狩振興局", "level10": "札幌市"},
                                }
                            }
                        }
                    ]
                },
            )
        )
    )
    second = NominatimEnricher(NominatimOptions(countries=("JP",), retries=1), cache, client=healthy)
    second.prefetch([place])
    assert second.enrich(place, PlaceNames(geoname_id=1)).admin_1 == "北海道"
