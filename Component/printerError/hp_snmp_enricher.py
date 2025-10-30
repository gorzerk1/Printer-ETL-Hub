from __future__ import annotations
import os, ssl, json, re, argparse, sys, logging, platform
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
import urllib3
from bs4 import BeautifulSoup

xxx = "printers.json"
TARGET_TYPES = {"408dn", "MFP432"}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEBUG = False
LOGGER: Optional[logging.Logger] = None
LOG_ENABLED = True

def _project_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))

def _find_code_map_json(default_name: str = "codeErrorHp.json") -> str:
    candidates = [
        os.path.join(_project_root(), "data", default_name),
        os.path.join(os.getcwd(), default_name),
        os.path.join("/mnt/data", default_name),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return os.path.join(_project_root(), "data", default_name)

_CODE_CATALOG: Dict[str, Dict[str, str]] = {}

def _load_code_catalog(path: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    global _CODE_CATALOG
    if _CODE_CATALOG:
        return _CODE_CATALOG
    p = path or _find_code_map_json()
    mapping: Dict[str, Dict[str, str]] = {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    def _add_item(code: str, status: str, info: str):
        code = (code or "").strip()
        if not code:
            return
        mapping[code] = {"status": (status or "").strip().upper() or "INFO", "info": (info or "").strip()}
    items = raw
    if isinstance(raw, dict) and "items" in raw and isinstance(raw["items"], list):
        items = raw["items"]
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            _add_item(it.get("code", ""), it.get("status", ""), it.get("info", ""))
    elif isinstance(items, dict):
        for code, val in items.items():
            if isinstance(val, dict):
                _add_item(code, val.get("status", ""), val.get("info", ""))
    _CODE_CATALOG = mapping
    return _CODE_CATALOG

def _catalog_status_to_rank(status: Optional[str]) -> int:
    s = (status or "").strip().upper()
    if s == "CRITICAL": return 9
    if s == "ATTENTION": return 5
    if s == "INFO": return 1
    return 0

def _triage_three(sev: Optional[str]) -> str:
    if sev is None:
        return "informational"
    s = str(sev).strip()
    if s.isdigit():
        n = int(s)
        if n >= 6: return "critical"
        if n >= 3: return "warning"
        return "informational"
    s = s.lower()
    if s in {"critical", "fatal", "severe", "error"}:
        return "critical"
    if s in {"attention", "warning", "warn"}:
        return "warning"
    if s in {"info", "informational", "notice"}:
        return "informational"
    return "informational"

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

def _norm(x: Any) -> str:
    return str(x).strip() if x is not None else ""

def _matches_type(type_str: Optional[str]) -> bool:
    if not type_str:
        return False
    t = str(type_str).strip()
    if t in TARGET_TYPES:
        return True
    tl = t.lower()
    return any(s.lower() in tl for s in TARGET_TYPES)

def _iter_groups(data: Dict[str, Any]):
    for key in ("Company_Grouped", "Branches_Grouped"):
        lst = data.get(key)
        if isinstance(lst, list):
            yield lst

def _cli_only_ip() -> str | None:
    argv = sys.argv
    ip = None
    for i, a in enumerate(argv):
        if a in ("-ip", "--ip") and i + 1 < len(argv):
            ip = argv[i + 1]
        elif a.startswith("--ip="):
            ip = a.split("=", 1)[1]
    return ip

def _cli_debug() -> bool:
    argv = [s.lower() for s in sys.argv]
    if "-d" in argv or "--debug" in argv:
        for a in argv:
            if a.startswith("--debug="):
                val = a.split("=",1)[1]
                return val in ("1","true","t","yes","y","on")
        return True
    return False

class LegacyTLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        except Exception:
            pass
        for c in ("DEFAULT:@SECLEVEL=0", "DEFAULT@SECLEVEL=0"):
            try:
                ctx.set_ciphers(c)
                break
            except ssl.SSLError:
                continue
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

def _session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", LegacyTLSAdapter())
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    return s

def _parse_json_text(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        import json5
        return json5.loads(text)
    except Exception:
        pass
    fixed = re.sub(r'([{\[,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*):', r'\1"\2"\3:', text)
    return json.loads(fixed)

CODE_RE = re.compile(r"\b[A-Z]\d-\d{3,5}\b")

def _extract_alerts_from_json(obj: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    def walk(v: Any):
        if isinstance(v, dict):
            kl = {k.lower(): k for k in v.keys()}
            cand: Dict[str, str] = {}
            for k in list(kl.keys()):
                if "severity" in k and isinstance(v[kl[k]], (str, int)):
                    cand["severity"] = str(v[kl[k]]).strip()
                if ("code" in k or "statuscode" in k or "errorcode" in k) and isinstance(v[kl[k]], (str, int, str)):
                    cand["status_code"] = str(v[kl[k]]).strip()
                if any(x in k for x in ["desc", "message", "detail", "reason"]) and isinstance(v[kl[k]], str):
                    cand["description"] = v[kl[k]].strip()
            if cand.get("description") or cand.get("status_code"):
                if "severity" not in cand:
                    cand["severity"] = "unknown"
                out.append({"severity": cand["severity"], "status_code": cand.get("status_code",""), "description": cand.get("description","")})
            for vv in v.values():
                walk(vv)
        elif isinstance(v, list):
            for it in v:
                walk(it)
        elif isinstance(v, str):
            m = CODE_RE.search(v)
            if m:
                out.append({"severity": "unknown", "status_code": m.group(0), "description": v.strip()})
    walk(obj)
    uniq, seen = [], set()
    for a in out:
        key = (a.get("severity",""), a.get("status_code",""), a.get("description",""))
        if key not in seen:
            uniq.append(a); seen.add(key)
    return uniq

def _extract_alerts_from_html(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    alerts: List[Dict[str, str]] = []
    rows = soup.select("div.x-grid3-body div.x-grid3-row") or soup.select("tr")
    for row in rows:
        cells = [c.get_text(strip=True) for c in row.select("div.x-grid3-cell-inner")] or [td.get_text(strip=True) for td in row.find_all("td")]
        if not cells:
            continue
        joined = " ".join(cells).lower()
        if "description" in joined and "status code" in joined:
            continue
        desc = max(cells, key=len).strip()
        code = ""
        m = CODE_RE.search(desc)
        if m:
            code = m.group(0)
            if desc.startswith(code):
                desc = desc[len(code):].lstrip(" :.-\u00a0")
        sev = ""
        img = row.find("img")
        if img and img.get("alt"):
            sev = img["alt"].strip()
        if not sev:
            short = [t for t in cells if t]
            if short:
                sev = min(short, key=len)
        if not sev:
            sev = "unknown"
        if desc or code:
            alerts.append({"severity": sev, "status_code": code, "description": desc})
    uniq, seen = [], set()
    for a in alerts:
        key = (a.get("severity",""), a.get("status_code",""), a.get("description",""))
        if key not in seen:
            uniq.append(a); seen.add(key)
    return uniq

def _session_probe_get(s: requests.Session, url: str, timeout: float = 12):
    r = s.get(url, verify=False, timeout=timeout)
    if r.status_code == 200 and r.text and "html" not in (r.headers.get("content-type","")).lower():
        if not r.encoding:
            r.encoding = r.apparent_encoding
        return r
    return r

def _fetch_alerts(ip: str) -> List[Dict[str, str]]:
    s = _session()
    out: List[Dict[str, str]] = []
    for base in (f"https://{ip}", f"http://{ip}"):
        dbg(f"[HTTP] probing {base}")
        try:
            s.get(f"{base}/sws/index.html", verify=False, timeout=10)
        except Exception:
            pass
        for path in (
            "/sws/app/information/activealert/activealert.json",
            "/sws/app/information/activealert/activeAlert.json",
            "/sws/app/information/activealert/active_alert.json",
            "/sws/app/information/activealert/alert.json",
        ):
            try:
                r = _session_probe_get(s, base + path)
                if r.status_code == 200 and r.text and "{" in r.text:
                    data = _parse_json_text(r.text)
                    alerts = _extract_alerts_from_json(data)
                    if alerts:
                        out = alerts
                        dbg(f"[ALERTS] {ip} json={len(out)}")
                        return out
            except Exception:
                continue
        try:
            r = s.get(f"{base}/sws/app/information/activealert/activealert.html", verify=False, timeout=12)
            if r.status_code == 200:
                if not r.encoding:
                    r.encoding = r.apparent_encoding
                alerts = _extract_alerts_from_html(r.text)
                if alerts:
                    out = alerts
                    dbg(f"[ALERTS] {ip} html={len(out)}")
                    return out
        except Exception:
            continue
    return out

def _severity_rank(sev: str) -> int:
    if sev is None:
        return 0
    s = str(sev).strip()
    if s.isdigit():
        return int(s)
    s = s.lower()
    if s in ("fatal","critical"): return 9
    if s in ("error","severe"): return 6
    if s in ("warning",): return 3
    if s == "attention": return 5
    if s in ("info","informational"): return 1
    return 0

def _pick_alert(alerts: List[Dict[str, str]]) -> Tuple[str, str, str]:
    """
    Choose most severe alert; if remote 'severity' is vague/unknown,
    fall back to our catalog's severity for the code.
    Returns (code, description, baseline_severity_three_levels)
    """
    if not alerts:
        return ("", "", "informational")
    code_map = _load_code_catalog()
    def rank(a: Dict[str, str]) -> Tuple[int, int]:
        r = _severity_rank(a.get("severity",""))
        if r == 0:
            code = a.get("status_code","")
            if code and code in code_map:
                r = _catalog_status_to_rank(code_map[code].get("status"))
        has_code = 1 if a.get("status_code") else 0
        return (r, has_code)
    pool = alerts[:]
    pool.sort(key=rank, reverse=True)
    top = pool[0]
    code = top.get("status_code","")
    desc = top.get("description","").strip()
    if not code:
        m = CODE_RE.search(desc or "")
        if m:
            code = m.group(0)
    base_sev = None
    if code and code in code_map:
        base_sev = _triage_three(code_map[code].get("status"))
    if not base_sev:
        base_sev = _triage_three(top.get("severity"))
    return (code, desc, base_sev)

def _short_label_for(code: str, desc: str) -> Tuple[str, Optional[str]]:
    """
    Returns (label, severity_from_catalog_or_none)
    """
    catalog = _load_code_catalog()
    if code and code in catalog:
        entry = catalog[code]
        return (entry.get("info") or "Check printer", entry.get("status") or None)
    d = (desc or "").strip().lower()
    if not d:
        return ("Normal", None)
    if "door" in d: return ("Door open", None)
    if "jam" in d: return ("Paper jam", None)
    if "toner" in d and "detect" in d: return ("Toner not detected", None)
    if "toner" in d and ("empty" in d or "end" in d): return ("Toner empty", None)
    if ("drum" in d) or ("imaging unit" in d):
        if "not" in d and "install" in d: return ("Drum not installed", None)
        if "end" in d or "replace" in d: return ("Replace drum now", None)
    if "transfer" in d: return ("Transfer roller fault", None)
    if "scanner" in d: return ("Scanner error", None)
    if "fuser" in d: return ("Fuser error", None)
    return ("Check printer", None)

def _normalize_problem_and_severity(problem: str) -> Tuple[str, Optional[str]]:
    """
    Apply requested overrides:
      - 'Normal' (or empty) => 'Ready' with severity 'informational'
      - any label containing 'sleep' => 'Sleeping' with severity 'informational'
    Returns (normalized_problem, forced_severity_or_None)
    """
    p = (problem or "").strip()
    low = p.lower()
    if p == "" or low == "normal":
        return ("Ready", "informational")
    if "sleep" in low:
        return ("Sleeping", "informational")
    return (p, None)

_offline_events: List[Tuple[str, str, str]] = []

def _enrich_item(item: Dict[str, Any], timeout: Optional[float]) -> bool:
    ip = _norm(item.get("Printer IP"))
    if not ip or ip.lower() in ("-", "null"):
        pi = item.setdefault("printerInfo", {})
        pi["status"] = "offline"
        pi["reason"] = "no IP"
        dbg(f"[MATCH] '{item.get('ID')}' no IP -> offline")
        _offline_events.append((str(item.get("ID")), ip or "-", "no IP"))
        return True
    dbg(f"[MATCH] enriching '{item.get('ID')}' ip={ip}")
    try:
        alerts = _fetch_alerts(ip) if timeout is None else _fetch_alerts(ip)
        code, desc, baseline_sev = _pick_alert(alerts)
        label, severity_from_catalog = _short_label_for(code, desc)
        label, forced_severity = _normalize_problem_and_severity(label)
        pi = item.setdefault("printerInfo", {})
        pi["status"] = "online"
        pe = pi.setdefault("printerError", {})
        pe["code"] = code
        pe["problem"] = label
        if forced_severity:
            pe["severity"] = forced_severity
        elif severity_from_catalog:
            pe["severity"] = _triage_three(severity_from_catalog)
        else:
            pe["severity"] = baseline_sev
        dbg(f"[JSON] '{item.get('ID')}' -> online, code={code or '-'} problem={label} sev={pe['severity']}")
    except Exception as e:
        reason = str(e)
        pi = item.setdefault("printerInfo", {})
        pi["status"] = "offline"
        pi["reason"] = reason
        _log_warn(f"[OFFLINE] ID='{item.get('ID')}' ip={ip} -> {reason}")
        _offline_events.append((str(item.get("ID")), ip, reason))
    return True

def _update_json_inplace(json_path: str, only_ip: Optional[str], timeout: Optional[float]) -> Tuple[int, int, int, List[Tuple[str, str, str]]]:
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
                    if typ and _matches_type(typ):
                        work.append(item)
    dbg(f"[JSON] selected={len(work)} only_ip={only_ip or '-'} timeout={timeout}")
    touched = 0
    for it in work:
        if _enrich_item(it, timeout):
            touched += 1
    online = sum(1 for it in work if isinstance(it.get("printerInfo"), dict) and it["printerInfo"].get("status") == "online")
    offline = sum(1 for it in work if isinstance(it.get("printerInfo"), dict) and it["printerInfo"].get("status") == "offline")
    tmp = json_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, json_path)
    dbg(f"[JSON] wrote {json_path}; touched={touched}")
    return touched, online, offline, list(_offline_events)

def _str2bool(v: str) -> bool:
    s = v.strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError("Boolean value expected (true/false).")

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Update printers.json with printer error code/label (HTTP web UI)")
    p.add_argument("-ip", dest="only_ip", help='Process only the matching "Printer IP" from printers.json (bypasses TARGET_TYPES)')
    p.add_argument("-t", "--timeout", dest="timeout", type=float, help="Per-printer timeout in seconds (default: internal timeouts)")
    p.add_argument("-d", "--debug", dest="debug", type=_str2bool, default=False, help="Debug logging to console: true|false (default: false)")
    p.add_argument("-l", "--log", dest="log", type=_str2bool, default=True, help="Write detailed log file: true|false (default: true)")
    p.add_argument("--catalog", dest="catalog", help="Path to code catalog JSON (default: data/codeErrorHp.json, also checks CWD and /mnt/data)")
    return p

def _print_unified_console_from_json():
    if _cli_debug():
        return
    try:
        path = _find_printers_json()
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return
    items: List[Dict[str, Any]] = []
    for lst in _iter_groups(data):
        items.extend(lst if isinstance(lst, list) else [])
    only_ip = _cli_only_ip()
    processed = online = offline = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        id_ = (item.get("ID") or item.get("Id") or item.get("id") or item.get("_id") or "-")
        ip = (item.get("Printer IP") or item.get("IP") or item.get("ip") or "-")
        if only_ip and str(ip).strip() != str(only_ip).strip():
            continue
        typ = item.get("Type")
        if not only_ip and not _matches_type(typ):
            continue
        pi = item.get("printerInfo") or {}
        status = str(pi.get("status") or "offline").lower()
        processed += 1
        if status == "online":
            online += 1
        else:
            offline += 1
        print(f"[ PRINTER {id_} ] {ip} — {status}")
        pe = pi.get("printerError") or {}
        code = pe.get("code") or ""
        problem = pe.get("problem") or ""
        sev = pe.get("severity") or ""
        if code or problem:
            suffix = f" ({problem})" if problem else ""
            if sev:
                print(f"  - {sev}: {code}{suffix}")
            else:
                print(f"  - {code}{suffix}")

def run() -> int:
    ap = _build_argparser()
    args = ap.parse_args()
    global DEBUG, LOG_ENABLED
    DEBUG = bool(args.debug)
    LOG_ENABLED = bool(args.log)
    logfile = _setup_file_logger()
    catalog_path = args.catalog or _find_code_map_json()
    _load_code_catalog(catalog_path)
    json_path = _find_printers_json()
    only_ip = args.only_ip
    timeout = args.timeout
    touched, online, offline, offline_items = _update_json_inplace(json_path, only_ip, timeout)
    if _cli_debug():
        print(f"[SUMMARY] processed={touched} online={online} offline={offline}")
    for _id, ip, reason in offline_items:
        _log_warn(f"[OFFLINE] {_id} ({ip}) -> {reason}")
    if logfile:
        _log_info(f"Log saved to: {logfile}")
        _log_info("=== run end ===")
    return 0

if __name__ == "__main__":
    rc = run()
    try:
        _print_unified_console_from_json()
    except Exception:
        pass
    raise SystemExit(rc)
