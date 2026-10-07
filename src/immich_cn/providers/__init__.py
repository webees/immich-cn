"""反向地理编码 provider 的注册与装配。"""

from __future__ import annotations

from immich_cn.logging_config import get_logger
from immich_cn.providers.amap import AmapEnricher
from immich_cn.providers.base import NameEnricher, ProviderChain
from immich_cn.providers.nominatim import NominatimEnricher
from immich_cn.settings import BuildOptions

logger = get_logger("providers")

__all__ = ["AmapEnricher", "NameEnricher", "NominatimEnricher", "ProviderChain", "build_chain"]


def build_chain(options: BuildOptions) -> ProviderChain:
    """根据命令行的 provider 选择装配增强链。

    离线层级表始终是基线，``amap`` / ``nominatim`` 只在显式启用时作为增强叠加，
    因此没有任何密钥时流水线依然可以完整跑通。
    """
    requested = options.provider
    provider = options.resolve_provider()
    if requested == "auto" and provider != "amap":
        # 静默降级会让「缺密钥 / 密钥改名 / secret 过期」看起来像一次成功构建：
        # 产物与显式 offline 完全相同，只有 manifest 里记着 provider=offline。
        logger.warning(
            "provider=auto 但没有可用的 AMAP_API_KEY，已回退到离线模式；"
            "产物与 provider=offline 完全相同，需要高德增强时请配置该环境变量"
        )
    enrichers: list[NameEnricher] = []
    if provider == "amap":
        enrichers.append(AmapEnricher.from_options(options))
    elif provider == "nominatim":
        enrichers.append(NominatimEnricher.from_options(options))
    elif provider != "offline":
        logger.warning("未知 provider %s，回退到离线模式", provider)
    return ProviderChain(enrichers)
