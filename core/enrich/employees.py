from __future__ import annotations
from typing import Any, Dict, List, Tuple

def build_employees_index(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    return {str(e.get("id","")).strip(): {"name": e.get("name",""), "phone": e.get("phone","")} for e in items}

def apply_employees(data: Dict[str, Any], items: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], int]:
    index = build_employees_index(items)
    arr = data.get("Branches_Grouped")
    if not isinstance(arr, list):
        return data, 0
    updated = 0
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        rid = str(entry.get("ID","")).strip()
        emp = index.get(rid)
        if not emp:
            continue
        store = entry.get("storeInfo")
        if not isinstance(store, dict):
            store = {}
            entry["storeInfo"] = store
        before_name = store.get("Manager","")
        before_phone = store.get("Phone","")
        if emp.get("name"):
            store["Manager"] = emp["name"]
        if emp.get("phone"):
            store["Phone"] = emp["phone"]
        after_name = store.get("Manager","")
        after_phone = store.get("Phone","")
        if (before_name != after_name) or (before_phone != after_phone):
            updated += 1
    return data, updated
