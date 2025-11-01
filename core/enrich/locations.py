from __future__ import annotations
from typing import Any, Dict, List, Tuple, Set
import re

EXCEL_BRANCH_ID_COL = "מס' סניף"
EXCEL_ADDRESS_COL = "כתובת"
EXCEL_PRIMARY_DESC_COL = "תאור שרות ראשי"
EXCEL_SECONDARY_DESC_COL = "תאור שרות משני"
EXCEL_SUBSCR_NUM_COL = "מספר מנוי"

def _safe_int(x: Any) -> int | None:
    try:
        if x is None or x == "":
            return None
        return int(float(str(x).strip()))
    except Exception:
        return None

def _norm_text(x: Any) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    return re.sub(r"\s+"," ",s)

def _split_postal(addr: str) -> Tuple[str, str | None]:
    if not addr:
        return "", None
    m = re.search(r"(\d{7})\s*$", addr)
    if not m:
        return addr.strip(), None
    postal = m.group(1)
    cleaned = re.sub(r"[\s,:-]*\d{7}\s*$","",addr).rstrip(" ,:-")
    return cleaned.strip(), postal

def apply_locations(printers: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    key = None
    branches = None
    for k, v in printers.items():
        if isinstance(v, list) and k.lower() == "branches_grouped":
            key = k
            branches = v
            break
    if not isinstance(branches, list):
        return printers
    addr_by_branch: Dict[int, str] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        bid = _safe_int(r.get(EXCEL_BRANCH_ID_COL))
        if bid is None:
            continue
        addr = "" if r.get(EXCEL_ADDRESS_COL) is None else str(r.get(EXCEL_ADDRESS_COL)).strip()
        if addr:
            addr_by_branch[bid] = addr
    pair_order_by_branch: Dict[int, List[Tuple[str, str]]] = {}
    subs_by_branch: Dict[int, Dict[Tuple[str, str], List[str]]] = {}
    seen_pairs_by_branch: Dict[int, Set[Tuple[str, str]]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        bid = _safe_int(r.get(EXCEL_BRANCH_ID_COL))
        if bid is None:
            continue
        p = _norm_text(r.get(EXCEL_PRIMARY_DESC_COL))
        s = _norm_text(r.get(EXCEL_SECONDARY_DESC_COL))
        if p is None and s is None:
            continue
        pair = (p or "", s or "")
        subs_list = subs_by_branch.setdefault(bid, {}).setdefault(pair, [])
        sub_num = _norm_text(r.get(EXCEL_SUBSCR_NUM_COL))
        if sub_num is not None:
            subs_list.append(sub_num)
        seen = seen_pairs_by_branch.setdefault(bid, set())
        if pair not in seen:
            seen.add(pair)
            pair_order_by_branch.setdefault(bid, []).append(pair)
    for i, obj in enumerate(branches):
        if not isinstance(obj, dict):
            continue
        branch_id = _safe_int(obj.get("ID") or obj.get("Id") or obj.get("id"))
        if branch_id is None:
            continue
        si = obj.get("storeInfo")
        if not isinstance(si, dict):
            si = {}
        addr = addr_by_branch.get(branch_id, "")
        if addr:
            location, postal = _split_postal(addr)
            si["Location"] = location
            si["Postal"] = postal
        order = pair_order_by_branch.get(branch_id, [])
        subs_map = subs_by_branch.get(branch_id, {})
        def _make_desc(pair: Tuple[str, str]) -> Dict[str, str]:
            p, s = pair
            nums = subs_map.get(pair, [])
            line_id = nums[0] if nums else ""
            return {"LineID": str(line_id), "PrimaryDescription": p, "SecondayDescription": s}
        if len(order) >= 1:
            si["firstDescription"] = _make_desc(order[0])
        if len(order) >= 2:
            si["secondDescription"] = _make_desc(order[1])
        if "firstDisc" in si:
            del si["firstDisc"]
        if "secondDisc" in si:
            del si["secondDisc"]
        obj["storeInfo"] = si
        branches[i] = obj
    printers[key] = branches
    return printers
