# core/excel/update_from_json.py
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Set
import re
from datetime import datetime

_ILLEGAL_XML_CHARS_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F]')

def sanitize_excel_value(val):
    if val is None:
        return None
    if isinstance(val, str):
        return _ILLEGAL_XML_CHARS_RE.sub("", val)
    return val

def canonicalize_id(v) -> Optional[str]:
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(int(v))
    except Exception:
        pass
    s = str(v).strip().replace("\n", " ").replace("\r", " ").strip()
    return s

def normalize_color(name: str) -> Optional[str]:
    if not name:
        return None
    n = str(name).strip().lower()
    if "black" in n or n == "k":
        return "Black"
    if "cyan" in n or n == "c":
        return "Cyan"
    if "magenta" in n or n == "m":
        return "Magenta"
    if "yellow" in n or n == "y":
        return "Yellow"
    return None

def _status_online_offline(raw) -> str:
    if raw is None:
        return "offline"
    s = str(raw).strip().lower()
    if not s:
        return "offline"
    online_keys = ("online","ready","idle","sleep","printing","working","active","ok","connected")
    offline_keys = ("offline","down","disconnected","error","unknown","not reachable","unreachable","no connection","disabled")
    if any(k in s for k in online_keys):
        return "online"
    if any(k in s for k in offline_keys):
        return "offline"
    if "off" in s:
        return "offline"
    if "on" in s:
        return "online"
    return "offline"

def dash_if_blank(val):
    if val is None:
        return "-"
    if isinstance(val, str) and not val.strip():
        return "-"
    return val

def _iter_printers(obj):
    if isinstance(obj, dict):
        if "ID" in obj and isinstance(obj.get("printerInfo"), dict):
            yield obj
        for v in obj.values():
            yield from _iter_printers(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _iter_printers(x)

def extract_info(prn: Dict[str, Any]) -> Dict[str, Any]:
    # same as old script
    info = {"Status": None, "Black": None, "Cyan": None, "Magenta": None, "Yellow": None, "Error": None, "Severity": None, "Toner Type": None}
    pinfo = prn.get("printerInfo") or {}
    status_val = pinfo.get("status")
    if status_val is None:
        carts = pinfo.get("cartridges") or []
        if carts and isinstance(carts, list):
            first = carts[0] or {}
            status_val = first.get("status")
    info["Status"] = _status_online_offline(status_val)
    carts = pinfo.get("cartridges") or []
    for cart in carts:
        try:
            cname = normalize_color(cart.get("cartridge"))
            if not cname:
                continue
            rp = cart.get("remaining_percent")
            if rp is None:
                value = None
            else:
                try:
                    value = float(rp)
                    if hasattr(value, "is_integer") and value.is_integer():
                        value = int(value)
                except Exception:
                    value = rp
            if info.get(cname) in (None, "-"):
                info[cname] = value
        except Exception:
            continue
    # error
    err = pinfo.get("printerError")
    if isinstance(err, dict):
        info["Error"] = err.get("problem") or err.get("error")
        info["Severity"] = err.get("severity")
    # toner type
    tt = pinfo.get("tonerType")
    if isinstance(tt, (list, tuple)):
        seen = []
        for x in tt:
            s = str(x).strip()
            if s and s not in seen:
                seen.append(s)
        info["Toner Type"] = ", ".join(seen) if seen else None
    elif isinstance(tt, str):
        info["Toner Type"] = tt.strip() or None
    return info

def build_id_map(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    id_map: Dict[str, Dict[str, Any]] = {}
    for obj in _iter_printers(data):
        cid = canonicalize_id(obj.get("ID"))
        if not cid:
            continue
        info = extract_info(obj)
        # simple overwrite is fine
        id_map[cid] = info
    return id_map

def find_header_row_and_map(ws) -> tuple[Optional[int], Dict[str, int]]:
    max_scan_rows = min(max(ws.max_row, 1), 20)
    expected = {"id","status","black","cyan","magenta","yellow","error","severity","toner type","type"}
    best_row = None
    best_score = -1
    best_map: Dict[str, int] = {}
    for r in range(1, max_scan_rows + 1):
        row_map: Dict[str, int] = {}
        score = 0
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if v is None:
                continue
            name = str(v).strip()
            if not name:
                continue
            row_map[name] = c
            if name.strip().lower() in expected:
                score += 1
        if "id" in {k.strip().lower() for k in row_map} and score > best_score:
            best_row = r
            best_score = score
            best_map = row_map
    if best_row is None:
        return None, {}
    return best_row, best_map

def ensure_columns(ws, header_row: int, header_map: Dict[str, int], required_cols: List[str]) -> Dict[str, int]:
    last_col = ws.max_column
    lower_map = {k.strip().lower(): v for k, v in header_map.items()}
    # upgrade "Type" → "Toner Type" if needed
    if "toner type" not in lower_map:
        type_cols: List[int] = []
        for c in range(1, ws.max_column + 1):
            v = ws.cell(header_row, c).value
            if isinstance(v, str) and v.strip().lower() == "type":
                type_cols.append(c)
        if type_cols:
            ws.cell(header_row, type_cols[0], "Toner Type")
            header_map["Toner Type"] = type_cols[0]
            lower_map["toner type"] = type_cols[0]
    for col_name in required_cols:
        if col_name.strip().lower() in lower_map:
            continue
        last_col += 1
        ws.cell(header_row, last_col, col_name)
        header_map[col_name] = last_col
        lower_map[col_name.strip().lower()] = last_col
    return header_map

def update_sheet(ws, id_map: Dict[str, Dict[str, Any]]) -> int:
    header_row, header_map = find_header_row_and_map(ws)
    if not header_row:
        return 0
    required_cols = ["Status", "Black", "Cyan", "Magenta", "Yellow", "Error", "Severity", "Toner Type"]
    header_map = ensure_columns(ws, header_row, header_map, required_cols)
    lower_map = {k.strip().lower(): v for k, v in header_map.items()}
    id_col = lower_map.get("id")
    if not id_col:
        return 0
    updates = 0
    for r in range(header_row + 1, ws.max_row + 1):
        rid_val = ws.cell(r, id_col).value
        cid = canonicalize_id(rid_val)
        if not cid:
            continue
        info = id_map.get(cid)
        if not info:
            continue
        for name in required_cols:
            col_idx = lower_map.get(name.strip().lower())
            if not col_idx:
                continue
            ws.cell(r, col_idx, sanitize_excel_value(dash_if_blank(info.get(name))))
        updates += 1
    return updates

def update_branches_grouped(ws, employees_index: Dict[str, Dict[str, Any]]) -> int:
    if ws.title != "Branches_Grouped":
        return 0
    header_row, header_map = find_header_row_and_map(ws)
    if not header_row:
        return 0
    required_cols = ["Contacts Name", "Contacts Phone"]
    header_map = ensure_columns(ws, header_row, header_map, required_cols)
    lower_map = {k.strip().lower(): v for k, v in header_map.items()}
    id_col = lower_map.get("id")
    if not id_col:
        return 0
    name_col = lower_map.get("contacts name")
    phone_col = lower_map.get("contacts phone")
    updates = 0
    for r in range(header_row + 1, ws.max_row + 1):
        rid_val = ws.cell(r, id_col).value
        cid = canonicalize_id(rid_val)
        if not cid:
            continue
        emp = employees_index.get(cid)
        if not emp:
            continue
        if name_col:
            ws.cell(r, name_col, sanitize_excel_value(dash_if_blank(emp.get("name"))))
        if phone_col:
            ws.cell(r, phone_col, sanitize_excel_value(dash_if_blank(emp.get("phone"))))
        updates += 1
    return updates
