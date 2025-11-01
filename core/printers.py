from __future__ import annotations
from typing import Any, Dict, Iterable, Set

GROUP_KEYS = ("Company_Grouped", "Branches_Grouped")

def iter_printers(data: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(data, dict):
        for key in GROUP_KEYS:
            arr = data.get(key)
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict):
                        yield item
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item

def ensure_printer_info(prn: Dict[str, Any]) -> Dict[str, Any]:
    pi = prn.get("printerInfo")
    if not isinstance(pi, dict):
        pi = {}
        prn["printerInfo"] = pi
    return pi

_BAD_IPS = {"", "-", "n/a", "na", "none", "0.0.0.0", "null"}

def norm_ip(prn: Dict[str, Any]) -> str:
    for key in ("Printer IP", "IP", "ip"):
        v = prn.get(key)
        if v:
            return str(v).strip()
    return ""

def is_good_ip(ip: str) -> bool:
    return bool(ip) and ip.strip().lower() not in _BAD_IPS

def matches_type(prn: Dict[str, Any], target_types_lc: Set[str]) -> bool:
    typ = str(prn.get("Type") or "").strip().lower()
    return bool(typ) and typ in target_types_lc
