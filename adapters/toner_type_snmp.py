# adapters/toner_type_snmp.py
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple
from adapters.snmp_client import walk_oid

SUPPLIES_TABLE_ROOT = "1.3.6.1.2.1.43.11.1.1"
COL_CLASS, COL_TYPE, COL_DESC = "4", "5", "6"
PRT_SUPPLY_TYPE_TONER = {3, 5, 6, 10, 21}

PAREN_CODE_RE = re.compile(r"\(([A-Z0-9\-]{3,})\)")
AFTER_HP_CODE_RE = re.compile(r"\bHP\b\W*([A-Z0-9\-]{3,})", re.I)
GEN_CODE_RE = re.compile(r"\b([A-Z][A-Z0-9\-]{2,})\b")

def _to_text(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        try:
            return val.decode("utf-8", "ignore").strip("\x00")
        except Exception:
            return val.decode("latin-1", "ignore").strip("\x00")
    s = str(val)
    if s.startswith("b'") and s.endswith("'"):
        return s[2:-1]
    if s.startswith('b"') and s.endswith('"'):
        return s[2:-1]
    return s

def _parse_supplies_oid(oid: str) -> Optional[Tuple[str, int]]:
    parts = oid.strip(".").split(".")
    try:
        for i in range(len(parts) - 5):
            if parts[i:i+4] == ["43", "11", "1", "1"]:
                return parts[i+4], int(parts[i+6])
    except Exception:
        return None
    return None

def _friendly_color_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    t = text.lower()
    if "black" in t or "שחור" in t:
        return "Black"
    if "cyan" in t or "ציאן" in t:
        return "Cyan"
    if "magenta" in t or "מג" in t:
        return "Magenta"
    if "yellow" in t or "צהוב" in t:
        return "Yellow"
    return None

def _extract_code(text: str) -> Optional[str]:
    m = PAREN_CODE_RE.search(text)
    if m:
        return m.group(1)
    m = AFTER_HP_CODE_RE.search(text)
    if m:
        token = m.group(1)
        if not re.fullmatch(r"\d{3}V", token):
            return token
    matches = list(GEN_CODE_RE.finditer(text.upper()))
    if matches:
        return matches[-1].group(1)
    return None

def get_snmp_toner_types(ip: str, *, community: str, timeout: Optional[float]) -> List[str]:
    rows: Dict[int, Dict[str, Any]] = {}
    for oid, value in walk_oid(ip, SUPPLIES_TABLE_ROOT, community=community, timeout=timeout):
        parsed = _parse_supplies_oid(oid)
        if not parsed:
            continue
        col, idx = parsed
        row = rows.setdefault(idx, {})
        if col in (COL_CLASS, COL_TYPE):
            try:
                row[col] = int(value)
            except Exception:
                row[col] = None
        elif col == COL_DESC:
            row[col] = _to_text(value) or ""

    toner_rows: List[Tuple[int, Dict[str, Any]]] = []
    for idx, r in rows.items():
        t = r.get(COL_TYPE)
        if isinstance(t, int) and t in PRT_SUPPLY_TYPE_TONER:
            toner_rows.append((idx, r))

    color_order = {"Black": 0, "Cyan": 1, "Magenta": 2, "Yellow": 3}
    pairs: List[Tuple[str, str]] = []
    seen = set()

    for idx, r in sorted(toner_rows, key=lambda t: t[0]):
        desc = r.get(COL_DESC) or ""
        if not desc or "hp" not in desc.lower():
            continue
        color = _friendly_color_from_text(desc)
        code = _extract_code(desc)
        if color and code:
            key = (color, code)
            if key not in seen:
                seen.add(key)
                pairs.append(key)

    pairs.sort(key=lambda p: (color_order.get(p[0], 99), p[1]))
    return [code for _, code in pairs]
