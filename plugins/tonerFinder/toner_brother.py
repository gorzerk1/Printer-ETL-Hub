# plugins/tonerFinder/toner_brother.py
from __future__ import annotations
import logging
from typing import Any, Dict, Optional, Tuple, List
from settings.arguments import build_plugin_parser
from plugins.base import load_context_from_args, save_context
from core.printers import iter_printers, ensure_printer_info, norm_ip, is_good_ip, matches_type
from adapters.brother_toner_web import get_brother_toner

LOG = logging.getLogger("toner_brother")

TARGET_TYPES = {
    "MFC-L9570CDW",
    "MFC-L6900DW",
}
TARGET_TYPES_LC = {s.lower() for s in TARGET_TYPES}

def _process_one_printer(prn: Dict[str, Any], *, timeout: Optional[float]) -> Tuple[str, List[Dict[str, Optional[str]]]]:
    ip = norm_ip(prn)
    if not is_good_ip(ip):
        return "offline", []
    return get_brother_toner(ip, timeout=timeout or 5.0)

def main() -> int:
    ap = build_plugin_parser("Enrich printers.json with Brother toner levels over HTTP")
    args = ap.parse_args()
    ctx, log_cm = load_context_from_args(args, "toner_brother")
    timeout = args.timeout or ctx.cfg.http_default_timeout
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    processed = 0
    selected = 0
    found_only_ip = False
    with log_cm:
        printers = list(iter_printers(ctx.data))
        if args.only_ip:
            for prn in printers:
                ip = norm_ip(prn)
                if ip == args.only_ip:
                    found_only_ip = True
                    selected += 1
                    try:
                        status, carts = _process_one_printer(prn, timeout=timeout)
                        info = ensure_printer_info(prn)
                        info["status"] = status
                        info["cartridges"] = carts
                        processed += 1
                        LOG.debug("[%s] %s carts=%d", ip or "-", status, len(carts))
                    except Exception as e:
                        info = ensure_printer_info(prn)
                        info["status"] = "offline"
                        info["cartridges"] = []
                        LOG.warning("[%s] error: %s", ip or "-", e)
            if not found_only_ip:
                prn = {"ID": "", "Type": "", "Printer IP": args.only_ip, "printerInfo": {}}
                try:
                    status, carts = _process_one_printer(prn, timeout=timeout)
                    LOG.info("[synthetic %s] %s carts=%d", args.only_ip, status, len(carts))
                except Exception as e:
                    LOG.warning("[synthetic %s] error: %s", args.only_ip, e)
        else:
            for prn in printers:
                ip = norm_ip(prn)
                if not is_good_ip(ip):
                    continue
                if not matches_type(prn, TARGET_TYPES_LC):
                    continue
                selected += 1
                try:
                    status, carts = _process_one_printer(prn, timeout=timeout)
                    info = ensure_printer_info(prn)
                    info["status"] = status
                    info["cartridges"] = carts
                    processed += 1
                    LOG.debug("[%s] %s carts=%d", ip, status, len(carts))
                except Exception as e:
                    info = ensure_printer_info(prn)
                    info["status"] = "offline"
                    info["cartridges"] = []
                    LOG.warning("[%s] error: %s", ip, e)
        LOG.info("toner_brother: selected=%s processed=%s", selected, processed)
    save_context(ctx)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
