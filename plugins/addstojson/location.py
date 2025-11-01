from __future__ import annotations
import json
import logging
from pathlib import Path
from settings.arguments import build_plugin_parser
from plugins.base import load_context_from_args, save_context
from adapters.location_source import read_locations_xlsx
from core.enrich.locations import apply_locations

DEFAULT_LOCATIONS_XLSX = r"\\st-filea\St-SystemIT\IT\Stores\בזק\stores\קווים בחנויות.xlsx"

def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]

def _locations_xlsx_path() -> Path:
    try:
        from settings import config as cfg
        v = getattr(cfg, "LOCATIONS_XLSX", None)
        if v:
            return Path(v)
    except Exception:
        pass
    return Path(DEFAULT_LOCATIONS_XLSX)

def main() -> int:
    ap = build_plugin_parser("Enrich printers.json with Location data")
    args = ap.parse_args()
    ctx, log_cm = load_context_from_args(args, "adds_location")
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    with log_cm:
        src = _locations_xlsx_path()
        rows = read_locations_xlsx(src)
        out_json = _project_root() / "data" / "locations.json"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        with out_json.open("w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        ctx.data = apply_locations(ctx.data, rows)
        if args.debug:
            print(f"locations: read {len(rows)} rows from {src}")
            print(f"locations: wrote {out_json}")
            print("locations: applied location info to printers.json")
    save_context(ctx)
    if args.debug:
        print(f"saved: {ctx.json_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
