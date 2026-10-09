"""OpenStreetMap Nominatim provider（可选，默认关闭）。"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from immich_cn.domain import Place, PlaceNames
from immich_cn.fetching import retry_delay
from immich_cn.logging_config import get_logger
from immich_cn.providers.base import apply_cached_levels, place_cache_key
from immich_cn.providers.cache import JsonlCache
from immich_cn.rate_limit import RateLimiter
from immich_cn.settings import USER_AGENT, BuildOptions, country_codes_env, positive_int_env

logger = get_logger("nominatim")

NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/reverse"
#: 默认只处理离线层级表覆盖不到、且数据量小的地区，避免触发使用条款限制。
DEFAULT_COUNTRIES = ("TW", "JP")


@dataclass(slots=True)
class NominatimOptions:
    countries: tuple[str, ...] = DEFAULT_COUNTRIES
    qps: int = 1
    retries: int = 3
    language: str = "zh-CN,zh;q=0.9,en;q=0.8"


class NominatimEnricher:
    """调用 Nominatim reverse API 获取行政层级。

    严格遵守 https://operations.osmfoundation.org/policies/nominatim/ ：
    单线程、默认 1 QPS、真实 User-Agent，并且结果会落盘缓存，避免重复请求。
    """

    name = "nominatim"

    def __init__(
        self,
        options: NominatimOptions,
        cache_path: Path,
        *,
        user_agent: str = USER_AGENT,
        client: httpx.Client | None = None,
    ) -> None:
        self._options = options
        self._cache = JsonlCache(cache_path)
        self._limiter = RateLimiter(options.qps)
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )

    @classmethod
    def from_options(cls, options: BuildOptions) -> NominatimEnricher:
        return cls(
            NominatimOptions(
                countries=country_codes_env("IMMICH_CN_NOMINATIM_COUNTRIES", DEFAULT_COUNTRIES),
                qps=positive_int_env("IMMICH_CN_NOMINATIM_QPS", 1),
            ),
            options.cache_dir / "nominatim-reverse.jsonl",
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def prefetch(self, places: Iterable[Place]) -> None:
        for place in places:
            if place.country_code not in self._options.countries:
                continue
            cached = self._cache.get(place_cache_key(place))
            if cached is not None and "_error" not in cached:
                continue
            result = self._query(place)
            if "_error" in result:
                # 瞬时故障不写负缓存，下次运行重试
                continue
            self._cache.put(place_cache_key(place), result)
        logger.info("Nominatim 预取完成，缓存共 %d 条", len(self._cache))

    def _query(self, place: Place) -> dict[str, str]:
        params = {
            "lat": place.columns[4],
            "lon": place.columns[5],
            "format": "geocodejson",
            "accept-language": self._options.language,
            "zoom": "18",
            "addressdetails": "1",
        }
        for attempt in range(1, self._options.retries + 1):
            self._limiter.acquire()
            try:
                response = self._client.get(NOMINATIM_ENDPOINT, params=params)
                if response.status_code == 200:
                    return _parse(response.json())
                logger.warning("Nominatim 返回 %s（第 %d 次）", response.status_code, attempt)
                if attempt < self._options.retries:
                    time.sleep(retry_delay(attempt, response=response))
            except (httpx.HTTPError, ValueError) as error:
                logger.warning("Nominatim 请求失败（第 %d 次）：%s", attempt, error)
                if attempt < self._options.retries:
                    time.sleep(retry_delay(attempt, error))
        return {"_error": "request-failed"}

    def enrich(self, place: Place, names: PlaceNames) -> PlaceNames:
        if place.country_code not in self._options.countries:
            return names
        cached = self._cache.get(place_cache_key(place))
        if not cached or "_error" in cached:
            return names
        apply_cached_levels(cached, names)
        return names


def _parse(payload: Any) -> dict[str, str]:
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list) or not features:
        return {"_error": "empty"}
    properties = features[0].get("properties") if isinstance(features[0], dict) else None
    geocoding = properties.get("geocoding") if isinstance(properties, dict) else None
    if not isinstance(geocoding, dict):
        return {"_error": "empty"}

    result: dict[str, str] = {}
    admin = geocoding.get("admin")
    if isinstance(admin, dict):
        ordered: list[tuple[int, str]] = []
        for key, value in admin.items():
            if not isinstance(key, str) or not key.startswith("level"):
                continue
            digits = key.removeprefix("level")
            if not digits.isdigit() or not isinstance(value, str):
                continue
            ordered.append((int(digits), value))
        ordered.sort()
        for index, (_, value) in enumerate(ordered[:4], start=1):
            result[f"admin_{index}"] = value
    country = geocoding.get("country")
    if isinstance(country, str):
        result["country"] = country
    if not result:
        return {"_error": "empty"}
    return result
