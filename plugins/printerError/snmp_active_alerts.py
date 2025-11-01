from __future__ import annotations
import logging
from typing import Any, Dict, Optional, Tuple
from settings.arguments import build_plugin_parser
from plugins.base import load_context_from_args, save_context
from core.printers import iter_printers, ensure_printer_info, norm_ip, is_good_ip, matches_type
from adapters.snmp_alerts import process_snmp_alerts

LOG = logging.getLogger("snmp_active_alerts")

TARGET_TYPES = {
    "E60055",
    "E60155",
    "E72525",
    "M527",
    "SL-M3820ND",
    "SL-M3870FD",
    "MFP-P57750-XC",
    "MFC-L9570CDW",
    "MFC-L6900DW",
}
TARGET_TYPES_LC = {s.lower() for s in TARGET_TYPES}

def _process_one_printer(prn: Dict[str, Any], *, community: str, timeout: Optional[float]) -> Tuple[str, str]:
    ip = norm_ip(prn)
    if not is_good_ip(ip):
        return "Normal", "informational"
    return process_snmp_alerts(ip, community=community, timeout=timeout)

def main() -> int:
    ap = build_plugin_parser("Enrich printers.json with SNMP active alerts")
    args = ap.parse_args()
    ctx, log_cm = load_context_from_args(args, "snmp_active_alerts")
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
                    selected += 1
                    try:
                        problem, sev = _process_one_printer(prn, community=community, timeout=timeout)
                        info = ensure_printer_info(prn)
                        info["printerError"] = {"problem": problem, "severity": sev}
                        processed += 1
                        LOG.debug("[%s] %s (%s)", ip, problem, sev)
                    except Exception as e:
                        info = ensure_printer_info(prn)
                        info["printerError"] = {"problem": "Offline", "severity": "critical"}
                        LOG.warning("[%s] error: %s", ip or "-", e)
            if not found_only_ip:
                prn = {"ID": "", "Type": "", "Printer IP": args.only_ip, "printerInfo": {}}
                try:
                    problem, sev = _process_one_printer(prn, community=community, timeout=timeout)
                    LOG.info("[synthetic %s] %s (%s)", args.only_ip, problem, sev)
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
                    problem, sev = _process_one_printer(prn, community=community, timeout=timeout)
                    info = ensure_printer_info(prn)
                    info["printerError"] = {"problem": problem, "severity": sev}
                    processed += 1
                    LOG.debug("[%s] %s (%s)", ip, problem, sev)
                except Exception as e:
                    info = ensure_printer_info(prn)
                    info["printerError"] = {"problem": "Offline", "severity": "critical"}
                    LOG.warning("[%s] error: %s", ip, e)
        LOG.info("snmp_active_alerts: selected=%s processed=%s", selected, processed)
    save_context(ctx)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
