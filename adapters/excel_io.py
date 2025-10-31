# adapters/excel_io.py
from __future__ import annotations
from pathlib import Path
import shutil
from datetime import datetime
import openpyxl

def resolve_xlsm(path_like: str | Path) -> Path:
    p = Path(path_like).expanduser()
    if not p.is_absolute():
        p = p.resolve()
    if p.suffix == "":
        p = p.with_suffix(".xlsm")
    if p.suffix.lower() != ".xlsm":
        raise SystemExit(f"Only .xlsm files are supported (got {p.suffix}).")
    return p

def copy_draft_to_prod(draft: Path, prod: Path) -> None:
    prod.parent.mkdir(parents=True, exist_ok=True)
    if draft.resolve() == prod.resolve():
        return
    shutil.copy2(draft, prod)

def open_workbook(path: Path):
    return openpyxl.load_workbook(filename=str(path), data_only=False, keep_vba=True)

def save_workbook(wb, path: Path) -> None:
    wb.save(str(path))

def backup_workbook(wb, logs_dir: Path) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    target = logs_dir / f"{ts}.xlsm"
    wb.save(str(target))
    return target
