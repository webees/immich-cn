"""provider 结果的磁盘缓存（JSONL，追加写）。"""

from __future__ import annotations

import json
from pathlib import Path

from immich_cn.logging_setup import get_logger

logger = get_logger("provider-cache")


class JsonlCache:
    """把 ``key -> payload`` 以追加 JSONL 的形式落盘。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict[str, str]] = {}
        self._loaded = False
        self._invalid_lines = 0

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        invalid = 0
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    invalid += 1
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    invalid += 1
                    continue
                if not isinstance(payload, dict):
                    invalid += 1
                    continue
                key = payload.get("key")
                value = payload.get("value")
                if isinstance(key, str) and isinstance(value, dict):
                    self._data[key] = {str(k): str(v) for k, v in value.items()}
                else:
                    invalid += 1
        self._invalid_lines = invalid
        if invalid:
            logger.warning("provider 缓存 %s 有 %d 行无法解析或结构不合法，已忽略", self.path.name, invalid)
        logger.info("载入 provider 缓存 %s：%d 条", self.path.name, len(self._data))

    def get(self, key: str) -> dict[str, str] | None:
        self.load()
        return self._data.get(key)

    def put(self, key: str, value: dict[str, str]) -> None:
        self.load()
        self._data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        prefix = ""
        if self.path.exists() and self.path.stat().st_size:
            with self.path.open("rb") as handle:
                handle.seek(-1, 2)
                if handle.read(1) != b"\n":
                    prefix = "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            if prefix:
                handle.write(prefix)
            handle.write(json.dumps({"key": key, "value": value}, ensure_ascii=False) + "\n")

    @property
    def invalid_lines(self) -> int:
        self.load()
        return self._invalid_lines

    def __len__(self) -> int:
        self.load()
        return len(self._data)
