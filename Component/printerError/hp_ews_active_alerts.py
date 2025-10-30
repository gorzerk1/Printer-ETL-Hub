#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, asyncio, json, os, sys, logging, platform
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List, Iterable
from puresnmp import Client, V2C, PyWrapper

TARGET_TYPES = {"E60055","E60155","E72525","M527","SL-M3820ND","SL-M3870FD","MFP-P57750-XC", "MFC-L9570CDW", "MFC-L6900DW"}
TARGET_TYPES_LC = {s.lower() for s in TARGET_TYPES}
ALERT_TABLE_ROOT = "1.3.6.1.2.1.43.18.1.1"
COL_SEVERITY, COL_TRAINING, COL_GROUP, COL_GROUPIDX, COL_LOCATION, COL_CODE, COL_DESC, COL_TIME = "2","3","4","5","6","7","8","9"
HR_PRN_ERRORSTATE_BASE = "1.3.6.1.2.1.25.3.5.1.2"
HR_BITS = [("lowPaper",0),("noPaper",1),("lowToner",2),("noToner",3),("doorOpen",4),("jammed",5),("offline",6),("serviceRequested",7),("inputTrayMissing",8),("outputTrayMissing",9),("markerSupplyMissing",10),("outputNearFull",11),("outputFull",12),("inputTrayEmpty",13),("overduePreventMaint",14)]

DEBUG = False
LOGGER: Optional[logging.Logger] = None
LOG_ENABLED = False

SUPPRESS_PHRASES = {"sleep mode on","power saver mode","מצב שינה פועל","genuine hp cartridge installed"}
HEB_EN = {"תוף שחור ברמה נמוכה מאוד":"Black drum very low","אי-התאמת גודל ב-מגש 1":"Tray 1 size mismatch","גודל בלתי צפוי ב-מגש 1":"Unexpected size in Tray 1","מושהה":"Paused","41.03.B1 גודל בלתי צפוי ב-מגש 1":"Unexpected size in Tray 1","66044":"Service requested"}

def _printer_error_obj(msg: str, sev: Optional[str] = None) -> Dict[str, str]:
    if msg == "Normal":
        return {"problem": "Ready", "severity": "informational"}
    if msg == "Offline":
        return {"problem": "Offline", "severity": "critical"}
    s = (sev or "").lower()
    if s not in {"informational", "warning", "critical"}:
        s = "warning"
    return {"problem": msg, "severity": s}

def _setup_file_logger() -> Optional[str]:
    if not LOG_ENABLED: return None
    here = Path(__file__).resolve().parent
    root = here.parents[1] if len(here.parents) > 1 else here
    logs_dir = root / "logs" / Path(__file__).stem.lower()
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = logs_dir / f"{ts}.log"
    logger = logging.getLogger(Path(__file__).stem.lower())
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    fh = logging.FileHandler(str(logfile), encoding="utf-8")
    fh.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s","%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    global LOGGER
    LOGGER = logger
    logger.info("=== %s start ===", Path(__file__).stem.lower())
    logger.info("Python   : %s", sys.version.replace("\n"," "))
    logger.info("Platform : %s (%s)", platform.platform(), platform.machine())
    logger.info("CWD      : %s", os.getcwd())
    logger.info("ARGV     : %r", sys.argv)
    return str(logfile)

def _log(msg: str) -> None:
    if LOGGER is not None: LOGGER.info(msg)

def dbg(*args: Any) -> None:
    s = " ".join(str(a) for a in args)
    if DEBUG: print(s, flush=True)
    _log(s)

def _find_printers_json() -> str:
    cwd = Path(os.getcwd()) / "printers.json"
    if cwd.is_file(): return str(cwd)
    here = Path(__file__).resolve().parent
    candidate = here.parents[1] / "printers.json"
    return str(candidate if candidate.is_file() else cwd)

def _community(cli: Optional[str]) -> str:
    return cli or os.environ.get("SNMP_COMMUNITY","public")

def _to_text(v: Any) -> str:
    if hasattr(v, "value"): v = v.value
    if isinstance(v, (bytes, bytearray)):
        try: return v.decode("utf-8","ignore")
        except Exception: return v.decode("latin-1","ignore")
    return str(v)

def _severity_tag(v: Optional[int]) -> str:
    try: i = int(v)
    except Exception: return "other"
    if i == 3: return "critical"
    if i in (4,5,6): return "warning"
    if i == 2: return "unknown"
    return "other"

_GROUP_MAP = {5:"generalPrinter",6:"cover",7:"localization",8:"input",9:"output",10:"marker",11:"markerSupplies",12:"markerColorant",13:"mediaPath",14:"channel",15:"interpreter",16:"consoleDisplayBuffer",17:"consoleLights",18:"alert"}
_CODE_MSG = {3:"Cover open",4:"Cover closed",8:"Paper jam",807:"Input tray low",808:"Input tray empty",903:"Output tray full",1001:"Fuser under temperature",1002:"Fuser over temperature",1101:"Toner empty",1104:"Toner almost empty",1109:"Waste toner full",1801:"Alert removed"}

def _clean_desc(desc: Optional[str]) -> Optional[str]:
    if not desc: return None
    d = desc.strip().strip('"').strip("'")
    if not d or d in {"?","??","\"\"","''"}: return None
    low = d.lower()
    for s in SUPPRESS_PHRASES:
        if s in low: return None
    if d in HEB_EN: d = HEB_EN[d]
    return d

def _mk_msg(severity: str, group_id: Optional[int], code_val: Optional[int], desc: Optional[str], group_idx: Optional[int]) -> Optional[str]:
    d = _clean_desc(desc)
    if isinstance(code_val,int) and code_val in _CODE_MSG:
        base = _CODE_MSG[code_val]
        if code_val == 1801: return None
        if group_id == 6 and isinstance(group_idx,int) and group_idx > 0 and "Cover" in base:
            return f"{base} (Cover #{group_idx})"
        return base
    if d: return d
    g = _GROUP_MAP.get(group_id or -1)
    if g == "cover": return "Cover issue"
    if g == "mediaPath": return "Paper path issue"
    if g == "markerSupplies": return "Supply issue"
    if g == "input": return "Input tray issue"
    if g == "output": return "Output tray issue"
    if g == "marker": return "Marker issue"
    return None

def _parse_alert_oid(oid: str) -> Optional[Tuple[str,str]]:
    s = oid.strip(".")
    base = ALERT_TABLE_ROOT
    if not s.startswith(base + "."): return None
    rest = s[len(base)+1:].split(".")
    if len(rest) < 3: return None
    col = rest[0]
    instance = rest[1] + "." + rest[2]
    return col, instance

async def _walk_alerts(host: str, community: str, timeout: Optional[float]) -> List[Tuple[str, Any]]:
    client = Client(host, V2C(community))
    client.configure(timeout=timeout if timeout and timeout > 0 else 6.0, retries=10)
    snmp = PyWrapper(client)
    out: List[Tuple[str, Any]] = []
    async for vb in snmp.walk(ALERT_TABLE_ROOT):
        out.append((vb.oid, vb.value))
    return out

def _hr_bits_as_flags(b: bytes) -> List[str]:
    flags: List[str] = []
    bitpos = 0
    for byt in b:
        for i in range(7, -1, -1):
            if ((byt >> i) & 1) == 1:
                for name, n in HR_BITS:
                    if n == bitpos:
                        flags.append(name)
                        break
            bitpos += 1
            if bitpos > 64: break
    return flags

def _flags_to_english(flags: List[str]) -> Optional[str]:
    if not flags: return None
    priority = ["doorOpen","jammed","noPaper","noToner","markerSupplyMissing","outputFull","inputTrayEmpty","serviceRequested","offline","lowPaper","lowToner","outputNearFull","overduePreventMaint","inputTrayMissing","outputTrayMissing"]
    label = {"doorOpen":"Door open","jammed":"Paper jam","noPaper":"No paper","noToner":"No toner","markerSupplyMissing":"Marker supply missing","outputFull":"Output bin full","inputTrayEmpty":"Input tray empty","serviceRequested":"Service requested","offline":"Printer offline","lowPaper":"Low paper","lowToner":"Low toner","outputNearFull":"Output bin near full","overduePreventMaint":"Preventive maintenance overdue","inputTrayMissing":"Input tray missing","outputTrayMissing":"Output tray missing"}
    for k in priority:
        if k in flags: return label[k]
    return label.get(flags[0], flags[0])

def _flags_severity(flags: List[str]) -> str:
    critical = {"doorOpen","jammed","noPaper","noToner","markerSupplyMissing","outputFull","inputTrayEmpty","serviceRequested","offline"}
    warning = {"lowPaper","lowToner","outputNearFull","overduePreventMaint","inputTrayMissing","outputTrayMissing"}
    if any(f in critical for f in flags):
        return "critical"
    if any(f in warning for f in flags):
        return "warning"
    return "informational"

async def _hr_errorstate_msg(host: str, community: str, timeout: Optional[float]) -> Optional[Tuple[str, str]]:
    client = Client(host, V2C(community))
    client.configure(timeout=timeout if timeout and timeout > 0 else 6.0, retries=3)
    snmp = PyWrapper(client)
    for idx in (1,2,3,4):
        oid = f"{HR_PRN_ERRORSTATE_BASE}.{idx}"
        try:
            val = await snmp.get(oid)
            if isinstance(val, (bytes, bytearray)) and len(val) > 0:
                flags = _hr_bits_as_flags(val)
                label = _flags_to_english(flags)
                if label:
                    return label, _flags_severity(flags)
        except Exception:
            continue
    return None

async def _fetch_alerts(host: str, community: str, timeout: Optional[float]) -> Tuple[str, str]:
    vbs = await _walk_alerts(host, community, timeout)
    rows: Dict[str, Dict[str, Any]] = {}
    for oid, value in vbs:
        parsed = _parse_alert_oid(str(oid))
        if not parsed: continue
        col, inst = parsed
        row = rows.setdefault(inst, {})
        if col in (COL_SEVERITY, COL_TRAINING, COL_GROUP, COL_GROUPIDX, COL_LOCATION, COL_CODE, COL_TIME):
            try: row[col] = int(value)
            except Exception: pass
        elif col == COL_DESC:
            txt = _to_text(value).strip()
            if txt != "": row[col] = txt
    chosen_msg: Optional[str] = None
    chosen_tag: Optional[str] = None
    for severity_pick in ("critical","warning","other","unknown"):
        for _, r in sorted(rows.items()):
            if _severity_tag(r.get(COL_SEVERITY)) != severity_pick: continue
            msg = _mk_msg(severity_pick, r.get(COL_GROUP), r.get(COL_CODE), r.get(COL_DESC), r.get(COL_GROUPIDX))
            if msg:
                chosen_msg = msg
                chosen_tag = severity_pick
                break
        if chosen_msg: break
    if chosen_msg:
        final_sev = "critical" if chosen_tag == "critical" else "warning"
        return chosen_msg, final_sev
    hr = await _hr_errorstate_msg(host, community, timeout)
    if hr:
        return hr
    return "Normal", "informational"

def _items_from_any_json(data: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(data, dict):
        for top_key in ("Company_Grouped", "Branches_Grouped"):
            arr = data.get(top_key)
            if isinstance(arr, list):
                for it in arr:
                    if isinstance(it, dict):
                        yield it
        return
    if isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                yield it
        return

def _get_ip(item: Dict[str, Any]) -> str:
    for key in ("Printer IP","IP","ip"):
        if key in item:
            v = str(item.get(key) or "").strip()
            if v: return v
    return ""

def _synthetic_item_for_ip(ip: str) -> Dict[str, Any]:
    return {"ID": "", "Type": "", "Printer IP": ip, "printerInfo": {}}

async def _enrich_item(item: Dict[str, Any], community: str, timeout: Optional[float]) -> Tuple[str,str,str]:
    pid = str(item.get("ID") or "")
    typ = str(item.get("Type") or "")
    ip = _get_ip(item)
    if not isinstance(item.get("printerInfo"), dict):
        item["printerInfo"] = {}
    dbg(f"=== ID='{pid or '-'}' Type='{typ or '-'}' IP={ip or '-'}===")
    if not ip or ip == "-":
        item["printerInfo"]["printerError"] = _printer_error_obj("Normal", "informational")
        dbg("[SKIP] no IP")
        return ("normal", "", "")
    try:
        coro = _fetch_alerts(ip, community, timeout)
        msg, sev = await asyncio.wait_for(coro, timeout=timeout) if timeout else await coro
        pe = _printer_error_obj(msg, sev)
        item["printerInfo"]["printerError"] = pe
        dbg(f"[{ip}] [ALERT] {pe['problem']}")
        dbg(f"[{ip}] [DONE] printerError={pe['problem']}")
        return ("normal", ip, msg) if msg == "Normal" else ("error", ip, msg)
    except Exception as e:
        item["printerInfo"]["printerError"] = _printer_error_obj("Offline", "critical")
        dbg(f"[{ip}] [ERROR] {e}")
        return ("offline", ip or "", "Offline")

async def _process(json_path: str, community: str, only_ip: Optional[str], timeout: Optional[float]) -> Tuple[int,int,int,int,int,List[Tuple[str,str]],List[str]]:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    items = list(_items_from_any_json(data))
    dbg(f"[JSON] discovered items: {len(items)}")
    work: List[Dict[str, Any]] = []
    if only_ip:
        for it in items:
            if _get_ip(it) == only_ip:
                work.append(it)
        if not work:
            dbg(f"[PLAN] JSON did not contain {only_ip}; using synthetic item")
            work.append(_synthetic_item_for_ip(only_ip))
    else:
        for it in items:
            t = str(it.get("Type") or "").strip()
            ip = _get_ip(it).strip()
            if not t or not ip or ip == "-": continue
            if t.lower() in TARGET_TYPES_LC:
                work.append(it)
    dbg(f"[PLAN] printers to process: {len(work)}")
    if not work:
        Path(json_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0,0,0,0,0,[],[]
    results = await asyncio.gather(*[asyncio.create_task(_enrich_item(it, community, timeout)) for it in work])
    tmp = json_path + ".tmp"
    Path(tmp).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, json_path)
    processed = len(work)
    normal_count = sum(1 for s,_,_ in results if s == "normal")
    error_rows = [(ip,msg) for s,ip,msg in results if s == "error"]
    error_count = len(error_rows)
    offline_ips = [ip for s,ip,_ in results if s == "offline" and ip]
    offline = len(offline_ips)
    online = processed - offline
    return processed, normal_count, error_count, online, offline, error_rows, offline_ips

def update_json_inplace(json_path: str, community: str, only_ip: Optional[str], timeout: Optional[float]) -> Tuple[int,int,int,int,int,List[Tuple[str,str]],List[str]]:
    return asyncio.run(_process(json_path, community, only_ip, timeout))

def _bool(v: str) -> bool:
    s = str(v).strip().lower()
    return s in {"1","true","t","yes","y","on"}

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("-ip", dest="only_ip")
    p.add_argument("-c","--community", dest="community")
    p.add_argument("-t","--timeout", dest="timeout", type=float)
    p.add_argument("-d","--debug", dest="debug", default="false")
    p.add_argument("-l","--log", dest="log", default="true")
    return p

def run() -> int:
    ap = _build_argparser()
    args = ap.parse_args()
    global DEBUG, LOG_ENABLED
    DEBUG = _bool(args.debug)
    LOG_ENABLED = _bool(args.log)
    logfile = _setup_file_logger()
    json_path = _find_printers_json()
    community = _community(args.community)
    dbg(f"[INPUT] json={json_path} community={community} only_ip={args.only_ip or '-'} timeout={args.timeout or '-'}")
    processed, normal_count, error_count, online, offline, error_rows, offline_ips = update_json_inplace(json_path, community, args.only_ip, args.timeout)
    print(f"[SUMMARY] normal={normal_count} errors={error_count} processed={processed} online={online} offline={offline}", flush=True)
    if DEBUG:
        if error_rows:
            print(f"[ERRORS] count={len(error_rows)}", flush=True)
            for ip, msg in error_rows:
                print(f"- {ip} — {msg}", flush=True)
        if offline_ips:
            print(f"[OFFLINE] count={len(offline_ips)}", flush=True)
            for ip in offline_ips:
                print(f"- {ip}", flush=True)
    if logfile: print(f"[LOG] {logfile}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(run())
