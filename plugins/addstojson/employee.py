from __future__ import annotations
import json
import logging
from pathlib import Path
from settings.arguments import build_plugin_parser
from plugins.base import load_context_from_args, save_context
from adapters.employee_source import read_employees_xlsx
from core.enrich.employees import apply_employees

def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]

def _employees_xlsx_path() -> Path:
    try:
        from settings import config as cfg
        v = getattr(cfg, "EMPLOYEES_XLSX", None)
        if v:
            return Path(v)
    except Exception:
        pass
    return _project_root() / "data" / "EmployeesData.xlsx"

def main() -> int:
    ap = build_plugin_parser("Enrich printers.json with Employees data")
    args = ap.parse_args()
    ctx, log_cm = load_context_from_args(args, "adds_employee")
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    with log_cm:
        src = _employees_xlsx_path()
        rows = read_employees_xlsx(src)
        out_json = _project_root() / "data" / "employeesData.json"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        with out_json.open("w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        ctx.data, updated = apply_employees(ctx.data, rows)
        if args.debug:
            print(f"employees: read {len(rows)} rows from {src}")
            print(f"employees: wrote {out_json}")
            print(f"employees: updated {updated} branches in printers.json")
    save_context(ctx)
    if args.debug:
        print(f"saved: {ctx.json_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
