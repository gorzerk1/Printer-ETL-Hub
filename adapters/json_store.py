# adapters/json_store.py
from __future__ import annotations
from pathlib import Path
import json
from typing import Any

class JsonStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Any:
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, data: Any) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)
