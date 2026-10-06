"""项目内统一的异常类型。"""

from __future__ import annotations


class ImmichCnError(Exception):
    """所有可预期错误的基类。"""


class SourceError(ImmichCnError):
    """上游数据源下载或校验失败。"""


class ParseError(ImmichCnError):
    """上游数据格式不符合预期。"""


class ConfigError(ImmichCnError):
    """配置或参数不合法。"""


class VerifyError(ImmichCnError):
    """数据校验未通过。"""
