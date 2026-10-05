"""WGS-84 与 GCJ-02 坐标转换。

高德地图使用 GCJ-02，而 GeoNames 使用 WGS-84，调用高德前必须转换。
算法为公开的通用实现，仅在国境范围内生效。
"""

from __future__ import annotations

import math

_A = 6378245.0
_EE = 0.00669342162296594323

# 粗略的国境范围，用于判断是否需要做偏移（不含港澳台以外的境外区域）。
_LON_MIN, _LON_MAX = 72.004, 137.8347
_LAT_MIN, _LAT_MAX = 0.8293, 55.8271


def out_of_china(longitude: float, latitude: float) -> bool:
    return not (_LON_MIN <= longitude <= _LON_MAX and _LAT_MIN <= latitude <= _LAT_MAX)


def _transform_latitude(longitude: float, latitude: float) -> float:
    value = -100.0 + 2.0 * longitude + 3.0 * latitude + 0.2 * latitude * latitude
    value += 0.1 * longitude * latitude + 0.2 * math.sqrt(abs(longitude))
    value += (20.0 * math.sin(6.0 * longitude * math.pi) + 20.0 * math.sin(2.0 * longitude * math.pi)) * 2.0 / 3.0
    value += (20.0 * math.sin(latitude * math.pi) + 40.0 * math.sin(latitude / 3.0 * math.pi)) * 2.0 / 3.0
    value += (160.0 * math.sin(latitude / 12.0 * math.pi) + 320 * math.sin(latitude * math.pi / 30.0)) * 2.0 / 3.0
    return value


def _transform_longitude(longitude: float, latitude: float) -> float:
    value = 300.0 + longitude + 2.0 * latitude + 0.1 * longitude * longitude
    value += 0.1 * longitude * latitude + 0.1 * math.sqrt(abs(longitude))
    value += (20.0 * math.sin(6.0 * longitude * math.pi) + 20.0 * math.sin(2.0 * longitude * math.pi)) * 2.0 / 3.0
    value += (20.0 * math.sin(longitude * math.pi) + 40.0 * math.sin(longitude / 3.0 * math.pi)) * 2.0 / 3.0
    value += (150.0 * math.sin(longitude / 12.0 * math.pi) + 300.0 * math.sin(longitude / 30.0 * math.pi)) * 2.0 / 3.0
    return value


def wgs84_to_gcj02(longitude: float, latitude: float) -> tuple[float, float]:
    """返回 ``(longitude, latitude)`` 的 GCJ-02 坐标。"""
    if out_of_china(longitude, latitude):
        return longitude, latitude
    delta_latitude = _transform_latitude(longitude - 105.0, latitude - 35.0)
    delta_longitude = _transform_longitude(longitude - 105.0, latitude - 35.0)
    rad_latitude = latitude / 180.0 * math.pi
    magic = math.sin(rad_latitude)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    delta_latitude = (delta_latitude * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    delta_longitude = (delta_longitude * 180.0) / (_A / sqrt_magic * math.cos(rad_latitude) * math.pi)
    return longitude + delta_longitude, latitude + delta_latitude
