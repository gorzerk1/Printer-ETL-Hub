# adapters/printers_store.py
from __future__ import annotations
from pathlib import Path
import json
import os
from typing import Any, Dict


def find_printers_json(explicit: str | None, *, project_root: Path) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()

    # 1) cwd
    cwd = Path.cwd() / "printers.json"
    if cwd.is_file():
        return cwd

    # 2) project root
    root_file = project_root / "printers.json"
    if root_file.is_file():
        return root_file

    # 3) env?
    env_p = os.getenv("PRINTERS_JSON")
    if env_p:
        p = Path(env_p).expanduser()
        return p if p.is_absolute() else (project_root / p)

    # fallback
    return root_file


def load_printers(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_printers(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
