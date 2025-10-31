# cli/convert_to_json.py
from __future__ import annotations
import argparse
import json
from pathlib import Path

from settings.config import AppConfig
from settings.logging_setup import setup_logging
from adapters.excel_io import resolve_xlsm, copy_draft_to_prod
from core.excel.import_from_xlsm import load_sheets, json_serializer

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert printers XLSM to JSON (draft -> prod -> json).")
    p.add_argument("--draft", help="path to draft xlsm (will be copied to prod)")
    p.add_argument("--prod", help="path to prod xlsm (will be overwritten)")
    p.add_argument("--output", "-o", help="output json path (defaults to prod.json)")
    p.add_argument("--sheets", nargs="+", default=["Company_Grouped", "Branches_Grouped"])
    p.add_argument("-l", "--logs", action="store_true", default=False)
    return p.parse_args()

def main() -> None:
    args = parse_args()
    cfg = AppConfig.load()   # no CLI overrides needed usually
    setup_logging(cfg.logs_dir, enable_logs=args.logs)

    draft_path = resolve_xlsm(args.draft or cfg.draft_xlsm)
    prod_path = resolve_xlsm(args.prod or cfg.printers_xlsm)

    # 1) copy draft → prod
    copy_draft_to_prod(draft_path, prod_path)

    # 2) read from prod and dump to JSON
    data = load_sheets(prod_path, args.sheets)

    out_path = Path(args.output).expanduser().resolve() if args.output else prod_path.with_suffix(".json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=json_serializer)

    print(f"Overwrote {prod_path} from {draft_path}")
    print(f"Wrote {out_path}")

if __name__ == "__main__":
    main()
