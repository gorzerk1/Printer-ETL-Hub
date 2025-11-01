# cli/convert_to_excel.py
from __future__ import annotations
import argparse
import json
from pathlib import Path

from settings.config import AppConfig
from settings.logging_setup import setup_logging
from adapters.excel_io import resolve_xlsm, open_workbook, save_workbook, backup_workbook
from core.excel.update_from_json import build_id_map, update_sheet, update_branches_grouped
from core.enrich.employees import build_employees_index

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Update printers XLSM from printers.json")
    p.add_argument("--json", help="path to printers.json (defaults to config)")
    p.add_argument("--xlsm", help="path to printers.xlsm (defaults to config)")
    p.add_argument("--employees-json", help="optional employeesData.json (defaults to data/employeesData.json)")
    p.add_argument("-u","--update", action="store_true", default=True, help="overwrite the XLSM in-place")
    p.add_argument("-l","--log", action="store_true", default=True, help="save a backup copy in logs/printerExcel")
    return p.parse_args()

def main() -> None:
    args = parse_args()
    cfg = AppConfig.load()
    setup_logging(cfg.logs_dir, enable_logs=True)

    json_path = Path(args.json).expanduser().resolve() if args.json else cfg.printers_json
    xlsm_path = resolve_xlsm(args.xlsm or cfg.printers_xlsm)
    employees_json = (
        Path(args.employees_json).expanduser().resolve()
        if args.employees_json
        else (cfg.data_dir / "employeesData.json")
    )

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    id_map = build_id_map(data)

    wb = open_workbook(xlsm_path)
    total_updates = 0
    for ws in wb.worksheets:
        total_updates += update_sheet(ws, id_map)

    if employees_json.exists():
        with employees_json.open("r", encoding="utf-8") as ef:
            employees_data = json.load(ef)
        employees_index = build_employees_index(employees_data)
        if "Branches_Grouped" in wb.sheetnames:
            ws_bg = wb["Branches_Grouped"]
            total_updates += update_branches_grouped(ws_bg, employees_index)

    if args.update:
        save_workbook(wb, xlsm_path)

    if args.log:
        backup_dir = cfg.logs_dir / "printerExcel"
        backup_path = backup_workbook(wb, backup_dir)
        print(f"Saved backup: {backup_path}")

    print(f"Updated rows: {total_updates}")

if __name__ == "__main__":
    main()
