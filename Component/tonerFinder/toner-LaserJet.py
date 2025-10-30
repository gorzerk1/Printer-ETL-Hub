from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
import logging
import platform
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, List, Union
from puresnmp import Client, V2C, PyWrapper
xxx = "printers.json"


TARGET_TYPES = {"M402dn", "M404dn", "M426fdn", "M426fdw", "M477fnw", "M521dn","E60055", "E60155", "E72525", "M527", "SL-M3820ND", "SL-M3870FD" , "MFP-P57750-XC", "408dn", "MFP432"}

SUPPLIES_TABLE_ROOT = "1.3.6.1.2.1.43.11.1.1"
COLORANT_TABLE_VALUE = "1.3.6.1.2.1.43.12.1.1.4"

COL_MARKER_IDX, COL_COLOR_IDX = "2", "3"
COL_CLASS, COL_TYPE, COL_DESC = "4", "5", "6"
COL_UNIT, COL_MAX, COL_LVL   = "7", "8", "9"

PRT_SUPPLY_TYPE_TONER = {3, 5, 6, 10, 21}
PRT_SUPPLY_UNIT_PERCENT = 19
NEG_UNKNOWN = {-1, -2, -3}

DEBUG = False
LOGGER: Optional[logging.Logger] = None
LOG_ENABLED = False

def _setup_file_logger() -> Optional[str]:
    if not LOG_ENABLED:
        return None
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", ".."))
    script_tag = os.path.splitext(os.path.basename(__file__))[0].lower()
    logs_dir = os.path.join(root, "logs", script_tag)
    os.makedirs(logs_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = os.path.join(logs_dir, f"{ts}.log")

    logger = logging.getLogger(script_tag)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    global LOGGER
    LOGGER = logger

    logger.info("=== %s start ===", script_tag)
    logger.info("Python   : %s", sys.version.replace("\n", " "))
    logger.info("Platform : %s %s (%s)", platform.system(), platform.release(), platform.machine())
    logger.info("CWD      : %s", os.getcwd())
    logger.info("ARGV     : %r", sys.argv)
    return logfile

def _force_stdout_utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def _log_info(msg: str) -> None:
    if LOGGER is not None:
        LOGGER.info(msg)

def _log_warn(msg: str) -> None:
    if LOGGER is not None:
        LOGGER.warning(msg)

def dbg(*args: Any) -> None:
    msg = " ".join(str(a) for a in args)
    if DEBUG:
        try:
            print(msg, flush=True)
        except Exception:
            pass
    _log_info(msg)

def _find_printers_json() -> str:
        return os.path.join(os.getcwd(), xxx)


def _community(cli_value: Optional[str]) -> str:
    if cli_value:
        return cli_value
    return os.environ.get("SNMP_COMMUNITY", "public")

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

def _norm(x: Any) -> str:
    return str(x).strip() if x is not None else ""

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

def _matches_type(type_str: Optional[str]) -> bool:
    if not type_str:
        return False
    t = str(type_str).strip()
    if t in TARGET_TYPES:
        return True
    tl = t.lower()
    return any(s.lower() in tl for s in TARGET_TYPES)

async def _fetch_printers_table(client: PyWrapper, root_oid: str) -> List[Tuple[str, Any]]:
    out: List[Tuple[str, Any]] = []
    async for vb in client.walk(root_oid):
        out.append((vb.oid, vb.value))
    return out

async def _fetch_printer_info(host: str, community: str) -> Optional[Dict[str, Any]]:
    dbg(f"[SNMP] host={host} community={community}")
    client = PyWrapper(Client(host, V2C(community)))
    supplies_vbs = await _fetch_printers_table(client, SUPPLIES_TABLE_ROOT)

    rows: Dict[int, Dict[str, Any]] = {}
    for oid, value in supplies_vbs:
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

    if DEBUG:
        dbg("[SNMP] Supplies rows (raw):")
        for i, r in sorted(rows.items()):
            dbg(f"  idx={i} type={r.get(COL_TYPE)} unit={r.get(COL_UNIT)} "
                f"max={r.get(COL_MAX)} lvl={r.get(COL_LVL)} desc='{r.get(COL_DESC)}'")

    toner_rows: List[Tuple[int, Dict[str, Any]]] = []
    for idx, r in rows.items():
        t = r.get(COL_TYPE)
        if isinstance(t, int) and t in PRT_SUPPLY_TYPE_TONER:
            toner_rows.append((idx, r))
    dbg(f"[SNMP] toner-like kept={len(toner_rows)}")

    color_map: Dict[Tuple[int, int], str] = {}
    try:
        color_vbs = await _fetch_printers_table(client, COLORANT_TABLE_VALUE)
        for oid, value in color_vbs:
            key = _parse_colorant_oid(oid)
            if not key:
                continue
            marker_idx, color_idx = key
            color_map[(marker_idx, color_idx)] = _to_text(value) or ""
    except Exception:
        color_map = {}

    cartridges: List[Dict[str, Any]] = []
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
        dbg(f"[SNMP] idx={idx} -> {entry}")
        cartridges.append(entry)

    return {"cartridges": cartridges}

def _iter_groups(data: Dict[str, Any]):
    for key in ("Company_Grouped", "Branches_Grouped"):
        lst = data.get(key)
        if isinstance(lst, list):
            yield lst

_offline_events: List[Tuple[str, str, str]] = []

async def _enrich_item(item: Dict[str, Any], community: str, timeout: Optional[float]) -> bool:
    ip = _norm(item.get("Printer IP"))
    if not ip or ip.lower() in ("-", "null"):
        item["printerInfo"] = {"status": "offline", "reason": "no IP"}
        dbg(f"[MATCH] '{item.get('ID')}' no IP -> offline")
        _offline_events.append((str(item.get("ID")), ip or "-", "no IP"))
        return True

    dbg(f"[MATCH] enriching '{item.get('ID')}' ip={ip}")
    try:
        if timeout is not None:
            info = await asyncio.wait_for(_fetch_printer_info(ip, community), timeout=timeout)
        else:
            info = await _fetch_printer_info(ip, community)

        carts = (info or {}).get("cartridges")
        if carts is not None:
            item["printerInfo"] = {"status": "online", "cartridges": carts}
        else:
            item["printerInfo"] = {"status": "online", "cartridges": []}
        dbg(f"[JSON] '{item.get('ID')}' -> online, carts={len(carts or [])}")
    except Exception as e:
        reason = str(e)
        item["printerInfo"] = {"status": "offline", "reason": reason}

        _log_warn(f"[OFFLINE] ID='{item.get('ID')}' ip={ip} -> {reason}")
        _offline_events.append((str(item.get("ID")), ip, reason))
    return True

async def _update_json_inplace_async(json_path: str, community: str, only_ip: Optional[str], timeout: Optional[float]) -> Tuple[int, int, int, List[Tuple[str, str, str]]]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    work: List[Dict[str, Any]] = []

    if only_ip:
        for lst in _iter_groups(data):
            for item in lst:
                if isinstance(item, dict) and _norm(item.get("Printer IP")) == only_ip:
                    work.append(item)
    else:
        for lst in _iter_groups(data):
            for item in lst:
                if isinstance(item, dict):
                    typ = item.get("Type")
                    if typ and (_matches_type(typ)):
                        work.append(item)

    dbg(f"[JSON] selected={len(work)} only_ip={only_ip or '-'} timeout={timeout}")

    touched = 0
    if work:
        tasks = [asyncio.create_task(_enrich_item(item, community, timeout)) for item in work]
        results = await asyncio.gather(*tasks)
        touched = sum(1 for r in results if r)

    online = sum(1 for it in work if isinstance(it.get("printerInfo"), dict) and it["printerInfo"].get("status") == "online")
    offline = sum(1 for it in work if isinstance(it.get("printerInfo"), dict) and it["printerInfo"].get("status") == "offline")

    tmp = json_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, json_path)
    dbg(f"[JSON] wrote {json_path}; touched={touched}")
    return touched, online, offline, list(_offline_events)

def update_json_inplace(json_path: str, community: str, only_ip: Optional[str], timeout: Optional[float]) -> Tuple[int, int, int, List[Tuple[str, str, str]]]:
    return asyncio.run(_update_json_inplace_async(json_path, community, only_ip, timeout))

def _str2bool(v: str) -> bool:
    s = v.strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError("Boolean value expected (true/false).")

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Update printers.json with SNMP toner info (Printer-MIB)")
    p.add_argument("-ip", dest="only_ip", help='Process only the matching "Printer IP" from printers.json (bypasses TARGET_TYPES)')
    p.add_argument("-c", "--community", dest="community", default=None, help="SNMP community (default: env SNMP_COMMUNITY or 'public')")
    p.add_argument("-t", "--timeout", dest="timeout", type=float, help="Per-printer timeout in seconds (default: no extra timeout)")
    p.add_argument("-d", "--debug", dest="debug", type=_str2bool, default=False, help="Debug logging to console: true|false (default: false)")
    p.add_argument("-l", "--log", dest="log", type=_str2bool, default=True, help="Write detailed log file: true|false (default: true)")
    return p

def run() -> int:
    ap = _build_argparser()
    args = ap.parse_args()

    global DEBUG, LOG_ENABLED
    DEBUG = bool(args.debug)
    LOG_ENABLED = bool(args.log)
    if DEBUG:
        _force_stdout_utf8()

    logfile = _setup_file_logger()

    json_path = _find_printers_json()
    community = _community(args.community)
    only_ip = args.only_ip
    timeout = args.timeout

    touched, online, offline, offline_items = update_json_inplace(json_path, community, only_ip, timeout)

    print(f"[SUMMARY] processed={touched} online={online} offline={offline}") if _cli_debug() else None
    if offline_items:
        print("[OFFLINE LIST]")
        for _id, ip, reason in offline_items:
            print(f"  - {_id} ({ip}) -> {reason}")

    _log_info("")
    _log_info(f"Summary: processed={touched} online={online} offline={offline}")
    for _id, ip, reason in offline_items:
        _log_warn(f"[OFFLINE] {_id} ({ip}) -> {reason}")
    if logfile:
        _log_info(f"Log saved to: {logfile}")
        _log_info("=== run end ===")

    return 0
def _cli_only_ip() -> str | None:
    import sys as _sys
    ip = None
    argv = _sys.argv
    for i, a in enumerate(argv):
        if a in ("-ip", "--ip") and i + 1 < len(argv):
            ip = argv[i + 1]
        elif a.startswith("--ip="):
            ip = a.split("=", 1)[1]
    return ip

def _cli_debug() -> bool:
    import sys as _sys
    argv = [s.lower() for s in _sys.argv]
    if "-d" in argv or "--debug" in argv:
        for a in argv:
            if a.startswith("--debug="):
                val = a.split("=",1)[1]
                return val in ("1","true","t","yes","y","on")
        return True
    return False

def _type_ok(item: dict) -> bool:
    typ = item.get("Type")
    try:
        return _matches_type(typ)
    except Exception:
        try:
            return (_norm_type(typ) in TARGET_TYPES)
        except Exception:
            return True

def _print_unified_console_from_json():
    if _cli_debug():
        return
    try:
        path = _find_printers_json()
    except Exception:
        try:
            import os as _os
            path = _os.path.join(_os.getcwd(), "printers.json")
        except Exception:
            return
    try:
        import json as _json
        with open(path, "r", encoding="utf-8") as fh:
            data = _json.load(fh)
    except Exception:
        return

    items = []
    try:
        for lst in _iter_groups(data):
            items.extend(lst if isinstance(lst, list) else [])
    except Exception:
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    items.extend(v)

    only_ip = _cli_only_ip()
    processed = online = offline = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        id_ = (item.get("ID") or item.get("Id") or item.get("id") or item.get("_id") or "-")
        ip = (item.get("Printer IP") or item.get("IP") or item.get("ip") or "-")
        if only_ip and str(ip).strip() != str(only_ip).strip():
            continue
        if not only_ip and not _type_ok(item):
            continue
        pi = item.get("printerInfo") or {}
        status = str(pi.get("status") or "offline").lower()
        carts = pi.get("cartridges") or []
        processed += 1
        if status == "online":
            online += 1
        else:
            offline += 1
        print(f"[ PRINTER {id_} ] {ip} — {status}")
        if status == "online" and isinstance(carts, list):
            for c in carts:
                try:
                    name = c.get("cartridge") or c.get("name") or c.get("color") or "Unknown"
                    pct  = c.get("remaining_percent")
                    pct_str = "N/A" if pct in (None, "") else str(pct)
                except Exception:
                    name, pct_str = "Unknown", "N/A"
                print(f"  - {name}: {pct_str}")
    print(f"[ SUMMARY ] processed={processed} online={online} offline={offline}")

if __name__ == "__main__":
    rc = run()
    try:
        _print_unified_console_from_json()
    except Exception:
        pass
    raise SystemExit(rc)