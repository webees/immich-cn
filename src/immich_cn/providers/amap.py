"""高德地图（Amap）反向地理编码 provider。"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from immich_cn.domain import Place, PlaceNames
from immich_cn.errors import ConfigError
from immich_cn.fetching import retry_delay
from immich_cn.logging_config import get_logger
from immich_cn.providers.base import apply_cached_levels, place_cache_key
from immich_cn.providers.cache import JsonlCache
from immich_cn.providers.geo import wgs84_to_gcj02
from immich_cn.rate_limit import RateLimiter
from immich_cn.settings import USER_AGENT, BuildOptions, country_codes_env, positive_int_env

logger = get_logger("amap")

AMAP_ENDPOINT = "https://restapi.amap.com/v3/geocode/regeo"
#: 高德对中国大陆以外区域支持有限，默认只处理这些国家码。
DEFAULT_COUNTRIES = ("CN", "HK", "MO")


@dataclass(slots=True)
class AmapOptions:
    api_key: str
    countries: tuple[str, ...] = DEFAULT_COUNTRIES
    qps: int = 3
    batch_size: int = 20
    radius: int = 1000
    retries: int = 3


class AmapEnricher:
    """调用高德批量逆地理编码接口，补充区县与乡镇粒度。"""

    name = "amap"

    def __init__(
        self,
        options: AmapOptions,
        cache_path: Path,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not options.api_key:
            raise ConfigError("启用 amap provider 需要 AMAP_API_KEY")
        self._options = options
        self._cache = JsonlCache(cache_path)
        self._limiter = RateLimiter(options.qps)
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": USER_AGENT},
        )

    @classmethod
    def from_options(cls, options: BuildOptions) -> AmapEnricher:
        api_key = options.amap_api_key
        if not api_key:
            raise ConfigError("启用 amap provider 需要设置环境变量 AMAP_API_KEY")
        countries = country_codes_env("IMMICH_CN_AMAP_COUNTRIES", DEFAULT_COUNTRIES)
        return cls(
            AmapOptions(
                api_key=api_key,
                countries=countries,
                qps=positive_int_env("IMMICH_CN_AMAP_QPS", 3),
                batch_size=positive_int_env("IMMICH_CN_AMAP_BATCH_SIZE", 20),
            ),
            options.cache_dir / "amap-regeo.jsonl",
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _redact(self, value: object) -> str:
        """抹掉日志中的 API Key。

        httpx 的异常消息会带上完整请求 URL（含 ``key=...``），
        在公共仓库里 Actions 日志任何人可见，必须避免把密钥写进日志。
        """
        text = str(value)
        secret = self._options.api_key
        if not secret:
            return text
        return text.replace(secret, "***").replace(quote(secret, safe=""), "***")

    # ---- prefetch -----------------------------------------------------

    def prefetch(self, places: Iterable[Place]) -> None:
        pending: list[Place] = []
        for place in places:
            if place.country_code not in self._options.countries:
                continue
            cached = self._cache.get(place_cache_key(place))
            # 只信任成功结果：旧的 _error 条目视为缓存失效，重新请求（自愈）
            if cached is not None and "_error" not in cached:
                continue
            pending.append(place)
            if len(pending) >= self._options.batch_size:
                self._query_batch(pending)
                pending = []
        if pending:
            self._query_batch(pending)
        logger.info("高德预取完成，缓存共 %d 条", len(self._cache))

    def _query_batch(self, batch: Sequence[Place]) -> None:
        coordinates: list[tuple[float, float]] = []
        for place in batch:
            longitude = float(place.columns[5])
            latitude = float(place.columns[4])
            coordinates.append(wgs84_to_gcj02(longitude, latitude))

        location = "|".join(f"{lon:.6f},{lat:.6f}" for lon, lat in coordinates)
        params = {
            "output": "json",
            "location": location,
            "key": self._options.api_key,
            "radius": str(self._options.radius),
            "extensions": "all",
            "batch": "true",
        }

        payload: dict[str, Any] | None = None
        for attempt in range(1, self._options.retries + 1):
            self._limiter.acquire()
            try:
                response = self._client.get(AMAP_ENDPOINT, params=params)
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as error:
                logger.warning(
                    "高德请求失败（第 %d/%d 次）：%s",
                    attempt,
                    self._options.retries,
                    self._redact(error),
                )
                if attempt < self._options.retries:
                    time.sleep(retry_delay(attempt, error))
                continue
            if isinstance(payload, dict) and payload.get("status") == "1":
                break
            logger.warning("高德返回异常状态：%s", self._redact(payload))
            payload = None
            if attempt < self._options.retries:
                time.sleep(retry_delay(attempt, response=response))

        if payload is None:
            # 瞬时故障不写负缓存：否则服务恢复后这些坐标会被永久跳过
            logger.warning("高德批量请求失败，本批 %d 个坐标下次运行重试", len(batch))
            return

        regeocodes = payload.get("regeocodes")
        if not isinstance(regeocodes, list) or len(regeocodes) != len(batch):
            if not isinstance(regeocodes, list):
                regeocodes = []
            logger.warning("高德返回数量与请求不一致：请求 %d，返回 %d", len(batch), len(regeocodes))

        for index, place in enumerate(batch):
            record = regeocodes[index] if index < len(regeocodes) else None
            levels = _parse_regeocode(record)
            if levels is None:
                logger.debug("高德未返回有效地址，跳过缓存以便下次重试")
            else:
                self._cache.put(place_cache_key(place), levels)

    # ---- enrich -------------------------------------------------------

    def enrich(self, place: Place, names: PlaceNames) -> PlaceNames:
        if place.country_code not in self._options.countries:
            return names
        cached = self._cache.get(place_cache_key(place))
        if not cached or "_error" in cached:
            return names
        apply_cached_levels(cached, names)
        if cached.get("country"):
            names.country = cached["country"]
        return names


def _parse_regeocode(record: object) -> dict[str, str] | None:
    if not isinstance(record, dict):
        return None
    address = record.get("addressComponent")
    if not isinstance(address, dict):
        return None

    def field(name: str) -> str:
        value = address.get(name)
        if isinstance(value, list):
            return ""
        return str(value) if value else ""

    province = field("province")
    city = field("city") or province
    district = field("district") or city
    township = field("township")
    parsed = {
        "country": field("country"),
        "admin_1": province,
        "admin_2": city,
        "admin_3": district,
        "admin_4": township,
    }
    if not any(parsed[f"admin_{level}"] for level in range(1, 5)):
        return None
    return parsed


__all__ = ["AMAP_ENDPOINT", "AmapEnricher", "AmapOptions"]
