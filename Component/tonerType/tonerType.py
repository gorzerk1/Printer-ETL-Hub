#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
import logging
import platform
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, List
from pathlib import Path
from puresnmp import Client, V2C, PyWrapper

TARGET_TYPES = {"M402dn","M404dn","M426fdn","M426fdw","M477fnw","M521dn","E60055","E60155","E72525","M527","MFP-P57750-XC","MFC-L9570CDW", "MFC-L6900DW", "SL-M3820ND"}
SUPPLIES_TABLE_ROOT = "1.3.6.1.2.1.43.11.1.1"
COL_CLASS, COL_TYPE, COL_DESC = "4", "5", "6"
PRT_SUPPLY_TYPE_TONER = {3,5,6,10,21}

DEBUG = False
LOGGER: Optional[logging.Logger] = None
LOG_ENABLED = False

HP_WORD_RE = re.compile(r"\bHP\b", re.I)
PAREN_CODE_RE = re.compile(r"\(([A-Z0-9\-]{3,})\)")
AFTER_HP_CODE_RE = re.compile(r"\bHP\b\W*([A-Z0-9\-]{3,})", re.I)
GEN_CODE_RE = re.compile(r"\b([A-Z][A-Z0-9\-]{2,})\b")

def _setup_file_logger() -> Optional[str]:
    if not LOG_ENABLED:
        return None
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    script_tag = Path(__file__).stem.lower()
    logs_dir = root / "logs" / script_tag
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = logs_dir / f"{ts}.log"
    logger = logging.getLogger(script_tag)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    fh = logging.FileHandler(str(logfile), encoding="utf-8")
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
    return str(logfile)

def _force_stdout_utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def _log(msg: str) -> None:
    if LOGGER is not None:
        LOGGER.info(msg)

def dbg(*args: Any) -> None:
    msg = " ".join(str(a) for a in args)
    if DEBUG:
        print(msg, flush=True)
    _log(msg)

def _find_printers_json() -> str:
    cwd = Path(os.getcwd()) / "printers.json"
    if cwd.is_file():
        return str(cwd)
    mnt = Path("/mnt/data/printers.json")
    if mnt.is_file():
        return str(mnt)
    here = Path(__file__).resolve().parent
    candidate = here.parents[1] / "printers.json"
    return str(candidate if candidate.is_file() else cwd)

def _community(cli_value: Optional[str]) -> str:
    return cli_value or os.environ.get("SNMP_COMMUNITY", "public")

def _to_text(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        try:
            return val.decode("utf-8", "ignore").strip("\x00")
        except Exception:
            return val.decode("latin-1", "ignore").strip("\x00")
    if hasattr(val, "value"):
        v = getattr(val, "value")
        return _to_text(v)
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
            if parts[i:i+4] == ["43","11","1","1"]:
                col = parts[i+4]
                idx = int(parts[i+6])
                return col, idx
    except Exception:
        return None
    return None

def _friendly_color_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    t = text.lower()
    if "black" in t or "שחור" in t: return "Black"
    if "cyan" in t or "ציאן" in t: return "Cyan"
    if "magenta" in t or "מג" in t: return "Magenta"
    if "yellow" in t or "צהוב" in t: return "Yellow"
    return None

def _matches_type(type_str: Optional[str]) -> bool:
    if not type_str:
        return False
    t = str(type_str).strip()
    if t in TARGET_TYPES:
        return True
    tl = t.lower()
    return any(s.lower() in tl for s in TARGET_TYPES)

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

async def _sysdescr(client: PyWrapper) -> Optional[str]:
    try:
        val = await client.get("1.3.6.1.2.1.1.1.0")
        return _to_text(val)
    except Exception:
        return None

async def _fetch_table(client: PyWrapper, root_oid: str) -> List[Tuple[str, Any]]:
    out: List[Tuple[str, Any]] = []
    async for vb in client.walk(root_oid):
        out.append((vb.oid, vb.value))
    return out

async def _fetch_tonertypes(host: str, community: str) -> Tuple[List[str], List[str]]:
    client = PyWrapper(Client(host, V2C(community)))
    lines: List[str] = []
    descr = await _sysdescr(client)
    if descr:
        lines.append(f"[OK] sysDescr: {descr[:120]}")
    else:
        lines.append("[WARN] sysDescr: no response")
    supplies_vbs = await _fetch_table(client, SUPPLIES_TABLE_ROOT)
    lines.append(f"[INFO] supplies rows: {len(supplies_vbs)}")
    rows: Dict[int, Dict[str, Any]] = {}
    for oid, value in supplies_vbs:
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
            txt = _to_text(value) or ""
            row[col] = txt
            lines.append(f"[DESC] {oid} -> {txt}")
    toner_rows: List[Tuple[int, Dict[str, Any]]] = []
    for idx, r in rows.items():
        t = r.get(COL_TYPE)
        if isinstance(t, int) and t in PRT_SUPPLY_TYPE_TONER:
            toner_rows.append((idx, r))

    # === CHANGE STARTS HERE (format + ordering only) ===
    # Collect (color, code) pairs, de-duplicated, then output just codes
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
                # keep the log informative; value still shows human-friendly text
                lines.append(f"[PARSED] idx={idx} -> {color} HP {code}")

    # sort BCMY, then by code for stability; output ONLY the codes
    pairs.sort(key=lambda p: (color_order.get(p[0], 99), p[1]))
    results: List[str] = [code for _, code in pairs]
    # === CHANGE ENDS HERE ===

    lines.append(f"[RESULT] {results if results else '[]'}")
    return results, lines

def _iter_groups(data: Dict[str, Any]):
    for key in ("Company_Grouped","Branches_Grouped"):
        lst = data.get(key)
        if isinstance(lst, list):
            yield lst

_offline_events: List[Tuple[str, str, str]] = []

async def _enrich_item(item: Dict[str, Any], community: str, timeout: Optional[float]) -> bool:
    pid = str(item.get("ID") or "")
    ptype = str(item.get("Type") or "")
    ip = str(item.get("Printer IP") or "").strip()
    if not isinstance(item.get("printerInfo"), dict):
        item["printerInfo"] = {}
    header = f"=== ID='{pid}' Type='{ptype}' IP={ip} ==="
    dbg(header)
    if not ip or ip.lower() in ("-","null"):
        item["printerInfo"]["tonerType"] = []
        dbg("[SKIP] no IP")
        _offline_events.append((pid or "-", ip or "-", "no IP"))
        return True
    try:
        async def do_fetch():
            res, lines = await _fetch_tonertypes(ip, community)
            for ln in lines:
                dbg(f"[{ip}] {ln}")
            return res
        toners = await asyncio.wait_for(do_fetch(), timeout=timeout) if timeout is not None else await do_fetch()
        item["printerInfo"]["tonerType"] = toners or []
        dbg(f"[{ip}] [DONE] tonerType={item['printerInfo']['tonerType']}")
    except Exception as e:
        item["printerInfo"]["tonerType"] = []
        dbg(f"[{ip}] [ERROR] {e}")
        _offline_events.append((pid or "-", ip, str(e)))
    return True

async def _update_by_type_async(data: Dict[str, Any], community: str, timeout: Optional[float]) -> Tuple[int,int,int,List[Tuple[str,str,str]]]:
    all_items: List[Dict[str, Any]] = []
    type_to_items: Dict[str, List[Dict[str, Any]]] = {}
    for lst in _iter_groups(data):
        for item in lst:
            if not isinstance(item, dict):
                continue
            typ = str(item.get("Type") or "").strip()
            if typ and _matches_type(typ):
                all_items.append(item)
                type_to_items.setdefault(typ, []).append(item)
    dbg(f"[PLAN] printers to process (by type): {len(all_items)} in {len(type_to_items)} types")
    type_to_toner: Dict[str, List[str]] = {}
    for typ, items in type_to_items.items():
        for it in items:
            pi = it.get("printerInfo")
            if isinstance(pi, dict):
                tt = pi.get("tonerType")
                if isinstance(tt, list) and tt:
                    type_to_toner[typ] = list(tt)
                    break
    fetch_jobs: List[asyncio.Task] = []
    job_meta: List[Tuple[str, str, str]] = []
    for typ, items in type_to_items.items():
        if typ in type_to_toner:
            continue
        representative = None
        for it in items:
            ip = str(it.get("Printer IP") or "").strip()
            if ip and ip.lower() not in ("-","null"):
                representative = (it, ip)
                break
        if not representative:
            _offline_events.append((str(items[0].get("ID") or "-"), "-", f"no IP for type {typ}"))
            type_to_toner[typ] = []
            continue
        it, ip = representative
        pid = str(it.get("ID") or "-")
        async def run_fetch(t=typ, ipaddr=ip, pidval=pid):
            try:
                async def do_fetch():
                    res, lines = await _fetch_tonertypes(ipaddr, community)
                    for ln in lines:
                        dbg(f"[{ipaddr}] {ln}")
                    return res
                toners = await asyncio.wait_for(do_fetch(), timeout=timeout) if timeout is not None else await do_fetch()
                type_to_toner[t] = toners or []
                dbg(f"[TYPE {t}] learned tonerType={type_to_toner[t]} from {ipaddr}")
            except Exception as e:
                type_to_toner[t] = []
                dbg(f"[{ipaddr}] [ERROR] {e}")
                _offline_events.append((pidval, ipaddr, str(e)))
        fetch_jobs.append(asyncio.create_task(run_fetch()))
        job_meta.append((typ, ip, pid))
    if fetch_jobs:
        await asyncio.gather(*fetch_jobs)
    for typ, items in type_to_items.items():
        tt = type_to_toner.get(typ, [])
        for it in items:
            if not isinstance(it.get("printerInfo"), dict):
                it["printerInfo"] = {}
            it["printerInfo"]["tonerType"] = list(tt)
    touched = len(all_items)
    online = sum(1 for it in all_items if isinstance(it.get("printerInfo"), dict) and (it["printerInfo"].get("tonerType") is not None))
    offline = len(_offline_events)
    return touched, online, offline, list(_offline_events)

async def _update_json_inplace_async(json_path: str, community: str, only_ip: Optional[str], timeout: Optional[float]) -> Tuple[int,int,int,List[Tuple[str,str,str]]]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if only_ip:
        work: List[Dict[str, Any]] = []
        for lst in _iter_groups(data):
            for item in lst:
                if isinstance(item, dict) and str(item.get("Printer IP") or "").strip() == only_ip:
                    work.append(item)
        dbg(f"[PLAN] printers to process: {len(work)}")
        touched = 0
        if work:
            tasks = [asyncio.create_task(_enrich_item(item, community, timeout)) for item in work]
            results = await asyncio.gather(*tasks)
            touched = sum(1 for r in results if r)
        online = sum(1 for it in work if isinstance(it.get("printerInfo"), dict) and (it["printerInfo"].get("tonerType") is not None))
        offline = len(_offline_events)
    else:
        touched, online, offline, _ = await _update_by_type_async(data, community, timeout)
    tmp = json_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, json_path)
    return touched, online, offline, list(_offline_events)

def update_json_inplace(json_path: str, community: str, only_ip: Optional[str], timeout: Optional[float]) -> Tuple[int,int,int,List[Tuple[str,str,str]]]:
    return asyncio.run(_update_json_inplace_async(json_path, community, only_ip, timeout))

def _str2bool(v: str) -> bool:
    s = v.strip().lower()
    if s in ("1","true","t","yes","y","on"): return True
    if s in ("0","false","f","no","n","off"): return False
    raise argparse.ArgumentTypeError("Boolean value expected (true/false).")

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Update printers.json with printerInfo.tonerType (Printer-MIB)")
    p.add_argument("-ip", dest="only_ip", help='Process only the matching "Printer IP" (bypasses TARGET_TYPES)')
    p.add_argument("-c","--community", dest="community", default=None, help="SNMP community (default: env SNMP_COMMUNITY or 'public')")
    p.add_argument("-t","--timeout", dest="timeout", type=float, help="Per-printer timeout in seconds")
    p.add_argument("-d","--debug", dest="debug", type=_str2bool, default=False, help="Debug logging to console: true|false")
    p.add_argument("-l","--log", dest="log", type=_str2bool, default=True, help="Write detailed log file: true|false")
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
    here_json = _find_printers_json()
    community = _community(args.community)
    only_ip = args.only_ip
    timeout = args.timeout
    dbg(f"[INPUT] json={here_json} community={community} only_ip={only_ip or '-'} timeout={timeout or '-'}")
    touched, online, offline, offline_items = update_json_inplace(here_json, community, only_ip, timeout)
    print(f"[SUMMARY] processed={touched} online={online} offline={offline}", flush=True)
    if offline_items:
        print("[OFFLINE LIST]", flush=True)
        for _id, ip, reason in offline_items:
            print(f"  - ID={_id} IP={ip} -> {reason}", flush=True)
    if logfile:
        print(f"[LOG] {logfile}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(run())
