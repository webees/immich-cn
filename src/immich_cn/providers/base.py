"""provider 的通用协议。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from immich_cn.domain import Place, PlaceNames
from immich_cn.logging_config import get_logger

logger = get_logger("providers")


@runtime_checkable
class NameEnricher(Protocol):
    """在离线层级表基础上补充或修正中文名的能力。"""

    name: str

    def prefetch(self, places: Iterable[Place]) -> None:
        """批量预取，便于把网络请求与逐条渲染解耦。"""

    def enrich(self, place: Place, names: PlaceNames) -> PlaceNames:
        """返回增强后的名称；无可用数据时应原样返回 ``names``。"""

    def close(self) -> None:
        """释放资源。"""


class ProviderChain:
    """按顺序叠加多个 provider，任意一个抛出异常都不应中断整体构建。"""

    def __init__(self, enrichers: Iterable[NameEnricher]) -> None:
        self._enrichers = list(enrichers)

    def __bool__(self) -> bool:
        return bool(self._enrichers)

    @property
    def names(self) -> list[str]:
        return [item.name for item in self._enrichers]

    def prefetch(self, places: Iterable[Place]) -> None:
        for enricher in self._enrichers:
            logger.info("预取 provider %s", enricher.name)
            enricher.prefetch(places)

    def enrich(self, place: Place, names: PlaceNames) -> PlaceNames:
        for enricher in self._enrichers:
            names = enricher.enrich(place, names)
        return names

    def close(self) -> None:
        for enricher in self._enrichers:
            enricher.close()

    def __enter__(self) -> ProviderChain:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
