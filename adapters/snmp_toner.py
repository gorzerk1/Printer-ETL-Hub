# adapters/snmp_toner.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from adapters.snmp_client import walk_oid

SUPPLIES_TABLE_ROOT = "1.3.6.1.2.1.43.11.1.1"
COLORANT_TABLE_VALUE = "1.3.6.1.2.1.43.12.1.1.4"

COL_MARKER_IDX, COL_COLOR_IDX = "2", "3"
COL_CLASS, COL_TYPE, COL_DESC = "4", "5", "6"
COL_UNIT, COL_MAX, COL_LVL = "7", "8", "9"

PRT_SUPPLY_TYPE_TONER = {3, 5, 6, 10, 21}
PRT_SUPPLY_UNIT_PERCENT = 19
NEG_UNKNOWN = {-1, -2, -3}

def _to_text(val: Any) -> Optional[str]:
    if val is None:
        return None
    try:
        if isinstance(val, (bytes, bytearray)):
            return val.decode("utf-8", "ignore").strip("\x00")
    except Exception:
        try:
            return val.decode("latin-1", "ignore").strip("\x00")
        except Exception:
            pass
    s = str(val)
    if s.startswith("b'") and s.endswith("'"):
        s = s[2:-1]
    elif s.startswith('b"') and s.endswith('"'):
        s = s[2:-1]
    return s

def _parse_supplies_oid(oid: str) -> Optional[Tuple[str, int]]:
    parts = oid.strip(".").split(".")
    try:
        for i in range(len(parts) - 5):
            if parts[i:i+4] == ["43", "11", "1", "1"]:
                col = parts[i+4]
                idx = int(parts[i+6])
                return col, idx
    except Exception:
        pass
    return None

def _parse_colorant_oid(oid: str) -> Optional[Tuple[int, int]]:
    parts = oid.strip(".").split(".")
    try:
        for i in range(len(parts) - 6):
            if parts[i:i+4] == ["43", "12", "1", "1"] and parts[i+4] == "4":
                if parts[i+5] != "1":
                    continue
                marker = int(parts[i+6])
                color = int(parts[i+7])
                return marker, color
    except Exception:
        pass
    return None

def _compute_percent(level: Optional[int], maxcap: Optional[int], unit: Optional[int]) -> Optional[int]:
    if level is None or level in NEG_UNKNOWN:
        return None
    if unit == PRT_SUPPLY_UNIT_PERCENT:
        return max(0, min(100, int(level)))
    if (maxcap is not None) and maxcap > 0 and level >= 0:
        pct = round(100.0 * float(level) / float(maxcap))
        return max(0, min(100, int(pct)))
    return None

def _pct_with_symbol(v: Optional[int]) -> Optional[str]:
    return None if v is None else f"{int(v)}%"

def _friendly_color(name: Optional[str], fallback_desc: Optional[str]) -> str:
    def pick(s: Optional[str]) -> Optional[str]:
        if not s:
            return None
        t = s.strip().lower()
        for k in ("black", "cyan", "magenta", "yellow", "gray", "grey", "photo black"):
            if k in t:
                return k
        he_map = {"שחור": "black", "צהוב": "yellow", "מגנטה": "magenta", "סיאן": "cyan"}
        for he, en in he_map.items():
            if he in t:
                return en
        return t
    c = pick(name) or pick(fallback_desc) or "unknown"
    return c.title()

def get_snmp_toner(ip: str, *, community: str, timeout: Optional[float]) -> Tuple[str, List[Dict[str, Optional[str]]]]:
    rows: Dict[int, Dict[str, Any]] = {}
    for oid, value in walk_oid(ip, SUPPLIES_TABLE_ROOT, community=community, timeout=timeout):
        parsed = _parse_supplies_oid(oid)
        if not parsed:
            continue
        col, idx = parsed
        row = rows.setdefault(idx, {})
        if col in (COL_CLASS, COL_TYPE, COL_UNIT, COL_MAX, COL_LVL, COL_MARKER_IDX, COL_COLOR_IDX):
            try:
                row[col] = int(value)
            except Exception:
                row[col] = None
        elif col == COL_DESC:
            row[col] = _to_text(value)

    toner_rows: List[Tuple[int, Dict[str, Any]]] = []
    for idx, r in rows.items():
        t = r.get(COL_TYPE)
        if isinstance(t, int) and t in PRT_SUPPLY_TYPE_TONER:
            toner_rows.append((idx, r))

    color_map: Dict[Tuple[int, int], str] = {}
    try:
        for oid, value in walk_oid(ip, COLORANT_TABLE_VALUE, community=community, timeout=timeout):
            key = _parse_colorant_oid(oid)
            if not key:
                continue
            marker_idx, color_idx = key
            color_map[(marker_idx, color_idx)] = _to_text(value) or ""
    except Exception:
        color_map = {}

    cartridges: List[Dict[str, Optional[str]]] = []
    for idx, r in sorted(toner_rows, key=lambda t: t[0]):
        level, maxcap, unit = r.get(COL_LVL), r.get(COL_MAX), r.get(COL_UNIT)
        percent_int = _compute_percent(level, maxcap, unit)
        marker_idx = r.get(COL_MARKER_IDX) or 1
        color_idx = r.get(COL_COLOR_IDX) or 0
        colorant_name = color_map.get((marker_idx, color_idx), None)
        desc = r.get(COL_DESC)
        entry = {
            "cartridge": _friendly_color(colorant_name, desc),
            "remaining_percent": _pct_with_symbol(percent_int),
        }
        cartridges.append(entry)

    status = "online" if cartridges is not None else "offline"
    return status, cartridges or []
