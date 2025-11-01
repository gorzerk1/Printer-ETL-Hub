# plugins/tonerType/toner_type_snmp.py
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from settings.arguments import build_plugin_parser
from plugins.base import load_context_from_args, save_context
from core.printers import iter_printers, ensure_printer_info, norm_ip, is_good_ip, matches_type
from adapters.toner_type_snmp import get_snmp_toner_types

LOG = logging.getLogger("toner_type_snmp")

TARGET_TYPES = {
    "M402dn","M404dn","M426fdn","M426fdw","M477fnw","M521dn",
    "E60055","E60155","E72525","M527","MFP-P57750-XC",
    "MFC-L9570CDW","MFC-L6900DW","SL-M3820ND"
}
TARGET_TYPES_LC = {s.lower() for s in TARGET_TYPES}

def _process_one(ip: str, *, community: str, timeout: Optional[float]) -> List[str]:
    if not is_good_ip(ip):
        return []
    return get_snmp_toner_types(ip, community=community, timeout=timeout)

def main() -> int:
    ap = build_plugin_parser("Enrich printers.json with toner type via SNMP")
    args = ap.parse_args()
    ctx, log_cm = load_context_from_args(args, "toner_type_snmp")
    community = args.community or ctx.cfg.snmp_default_community
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
                    if not matches_type(prn, TARGET_TYPES_LC):
                        continue
                    selected += 1
                    try:
                        codes = _process_one(ip, community=community, timeout=timeout)
                        info = ensure_printer_info(prn)
                        info["tonerType"] = codes or []
                        processed += 1
                        LOG.debug("[%s] %s", ip or "-", info["tonerType"])
                    except Exception as e:
                        LOG.warning("[%s] error: %s", ip or "-", e)
            if not found_only_ip:
                try:
                    codes = _process_one(args.only_ip, community=community, timeout=timeout)
                    LOG.info("[synthetic %s] %s", args.only_ip, codes)
                except Exception as e:
                    LOG.warning("[synthetic %s] error: %s", args.only_ip, e)
        else:
            by_type: Dict[str, List[Dict[str, Any]]] = {}
            for prn in printers:
                ip = norm_ip(prn)
                if not is_good_ip(ip):
                    continue
                if not matches_type(prn, TARGET_TYPES_LC):
                    continue
                t = str(prn.get("Type") or "").strip()
                by_type.setdefault(t, []).append(prn)
            for t, items in by_type.items():
                selected += len(items)
                preset: List[str] = []
                for it in items:
                    pi0 = it.get("printerInfo") or {}
                    tt0 = pi0.get("tonerType")
                    if isinstance(tt0, list) and tt0:
                        preset = list(tt0)
                        break
                if not preset:
                    rep_ip = None
                    for it in items:
                        ip = norm_ip(it)
                        if is_good_ip(ip):
                            rep_ip = ip
                            break
                    if rep_ip:
                        try:
                            preset = _process_one(rep_ip, community=community, timeout=timeout)
                        except Exception as e:
                            LOG.warning("[%s] error: %s", rep_ip, e)
                for it in items:
                    info = ensure_printer_info(it)
                    info["tonerType"] = list(preset)
                    processed += 1
        LOG.info("toner_type_snmp: selected=%s processed=%s", selected, processed)
    save_context(ctx)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
