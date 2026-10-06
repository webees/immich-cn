"""统一的日志初始化。"""

from __future__ import annotations

import logging
import os
import sys

LOGGER_NAME = "immich_cn"
_CONFIGURED = False


def get_logger(name: str | None = None) -> logging.Logger:
    """返回项目 logger；首次调用时完成初始化。"""
    global _CONFIGURED

    logger = logging.getLogger(LOGGER_NAME)
    if not _CONFIGURED:
        level = os.environ.get("IMMICH_CN_LOG_LEVEL", "INFO").upper()
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-7s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(level if level in logging.getLevelNamesMapping() else logging.INFO)
        logger.propagate = False
        _CONFIGURED = True

    if name:
        return logger.getChild(name)
    return logger


def configure(level: str, *, quiet: bool = False) -> None:
    """显式设置日志级别；``quiet`` 为真时只保留警告及以上。"""
    logger = get_logger()
    resolved = logging.WARNING if quiet else level.upper()
    logger.setLevel(resolved if resolved in logging.getLevelNamesMapping() else logging.INFO)
