"""immich-cn：为 Immich 构建中文反向地理编码数据的自动化流水线。"""

from __future__ import annotations

__all__ = ["SCHEMA_VERSION", "__version__"]

__version__ = "1.0.3"

#: geodata 制品清单的结构版本，与项目版本解耦，便于下游按结构解析。
SCHEMA_VERSION = 1
