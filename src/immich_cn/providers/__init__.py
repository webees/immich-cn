"""反向地理编码 provider 的注册与装配。"""

from __future__ import annotations

from immich_cn.config import BuildOptions
from immich_cn.logging_setup import get_logger
from immich_cn.providers.amap import AmapEnricher
from immich_cn.providers.base import NameEnricher, ProviderChain
from immich_cn.providers.nominatim import NominatimEnricher

logger = get_logger("providers")

__all__ = ["AmapEnricher", "NameEnricher", "NominatimEnricher", "ProviderChain", "build_chain"]


def build_chain(options: BuildOptions) -> ProviderChain:
    """根据命令行的 provider 选择装配增强链。

    离线层级表始终是基线，``amap`` / ``nominatim`` 只在显式启用时作为增强叠加，
    因此没有任何密钥时流水线依然可以完整跑通。
    """
    provider = options.resolve_provider()
    enrichers: list[NameEnricher] = []
    if provider == "amap":
        enrichers.append(AmapEnricher.from_options(options))
    elif provider == "nominatim":
        enrichers.append(NominatimEnricher.from_options(options))
    elif provider != "offline":
        logger.warning("未知 provider %s，回退到离线模式", provider)
    return ProviderChain(enrichers)
