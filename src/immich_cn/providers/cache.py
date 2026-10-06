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

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = payload.get("key")
                value = payload.get("value")
                if isinstance(key, str) and isinstance(value, dict):
                    self._data[key] = {str(k): str(v) for k, v in value.items()}
        logger.info("载入 provider 缓存 %s：%d 条", self.path.name, len(self._data))

    def get(self, key: str) -> dict[str, str] | None:
        self.load()
        return self._data.get(key)

    def put(self, key: str, value: dict[str, str]) -> None:
        self.load()
        self._data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"key": key, "value": value}, ensure_ascii=False) + "\n")

    def __len__(self) -> int:
        self.load()
        return len(self._data)
