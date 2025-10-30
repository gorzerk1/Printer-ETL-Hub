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

_TONER_PATTERNS = [
    r"W\d{4}[A-Z](?:X)?",
    r"MLT-[A-Z]\d{3,5}[A-Z]*",
    r"[A-Z]{2}\d{3}[A-Z]"
]
TONER_ID_RE = re.compile(r"(?:%s)" % "|".join(_TONER_PATTERNS))

SUPPLIES_PATHS = (
    "/sws/app/information/supplies/supplies.json",
    "/sws/app/information/supplies/supply.json",
    "/sws/app/information/home/home.json",
)

def _extract_toner_from_supplies_json(obj: Any) -> str:
    candidates: List[str] = []

    def walk(v: Any, ctx: str = ""):
        if isinstance(v, dict):
            for k, vv in v.items():
                k_low = str(k).lower()
                new_ctx = (ctx + " " + k_low).strip()
                if isinstance(vv, (str, int)):
                    s = str(vv).strip()
                    if ("toner" in new_ctx or "suppl" in new_ctx or k_low in ("id","model","name","partno","part_no","pn")):
                        m = TONER_ID_RE.search(s)
                        if m:
                            candidates.append(m.group(0))
                walk(vv, new_ctx)
        elif isinstance(v, list):
            for it in v:
                walk(it, ctx)
        elif isinstance(v, str):
            m = TONER_ID_RE.search(v)
            if m:
                candidates.append(m.group(0))

    walk(obj, "")
    for c in candidates:
        if c.startswith("W"):
            return c
    return candidates[0] if candidates else ""

def _extract_toner_from_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    m = TONER_ID_RE.search(text or "")
    return m.group(0) if m else ""

def _session_probe_get(s: requests.Session, url: str, timeout: float = 12) -> requests.Response:
    r = s.get(url, verify=False, timeout=timeout)
    if r.status_code == 200 and r.text:
        if not r.encoding:
            r.encoding = r.apparent_encoding
    return r

def _fetch_toner_name(ip: str, timeout: Optional[float] = None) -> str:
    s = _session()
    to = timeout or 12.0
    last_err: Optional[Exception] = None

    for scheme in ("https://", "http://"):
        base = f"{scheme}{ip}"
        dbg(f"[HTTP] probing supplies at {base}")
        try:
            s.get(f"{base}/sws/index.html", verify=False, timeout=to)
        except Exception:
            pass

        for path in SUPPLIES_PATHS:
            try:
                r = _session_probe_get(s, base + path, timeout=to)
                if r.status_code == 200 and r.text and ("{" in r.text or "[" in r.text):
                    try:
                        data = _parse_json_text(r.text)
                    except Exception:
                        data = None
                    if data is not None:
                        tid = _extract_toner_from_supplies_json(data)
                        if tid:
                            dbg(f"[SUPPLIES] {ip} -> tonerType={tid} (json via {path})")
                            return tid
                        m = TONER_ID_RE.search(r.text)
                        if m:
                            dbg(f"[SUPPLIES] {ip} -> tonerType={m.group(0)} (regex via {path})")
                            return m.group(0)
            except Exception as e:
                last_err = e
                continue

        for html_path in ("/sws/app/information/supplies/supplies.html",
                          "/sws/app/information/status/supplies.html",
                          "/sws/index.html"):
            try:
                r = s.get(base + html_path, verify=False, timeout=to)
                if r.status_code == 200 and r.text:
                    tid = _extract_toner_from_html(r.text)
                    if tid:
                        dbg(f"[SUPPLIES] {ip} -> tonerType={tid} (html via {html_path})")
                        return tid
            except Exception as e:
                last_err = e
                continue

    if last_err:
        raise last_err
    return ""

_offline_events: List[Tuple[str, str, str]] = []

def _enrich_item(item: Dict[str, Any], timeout: Optional[float]) -> bool:
    ip = _norm(item.get("Printer IP"))
    if not ip or ip.lower() in ("-", "null"):
        pi = item.setdefault("printerInfo", {})
        pi["status"] = "offline"
        pi["reason"] = "no IP"
        pi["tonerType"] = ""
        dbg(f"[MATCH] '{item.get('ID')}' no IP -> offline")
        _offline_events.append((str(item.get("ID")), ip or "-", "no IP"))
        return True

    dbg(f"[MATCH] enriching '{item.get('ID')}' ip={ip}")
    try:
        tid = _fetch_toner_name(ip, timeout)
        pi = item.setdefault("printerInfo", {})
        pi["status"] = "online"
        pi["tonerType"] = tid or ""
        if "printerError" in pi:
            try:
                del pi["printerError"]
            except Exception:
                pass
        dbg(f"[JSON] '{item.get('ID')}' -> online, tonerType={pi['tonerType'] or '-'}")
    except Exception as e:
        reason = str(e)
        pi = item.setdefault("printerInfo", {})
        pi["status"] = "offline"
        pi["reason"] = reason
        pi["tonerType"] = ""
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
        dbg(f"[JSON] selected={len(work)} only_ip={only_ip or '-'} timeout={timeout}")
        touched = 0
        for it in work:
            if _enrich_item(it, timeout):
                touched += 1
        online = sum(1 for it in work if isinstance(it.get("printerInfo"), dict) and it["printerInfo"].get("status") == "online")
        offline = sum(1 for it in work if isinstance(it.get("printerInfo"), dict) and it["printerInfo"].get("status") == "offline")
    else:
        for lst in _iter_groups(data):
            for item in lst:
                if isinstance(item, dict):
                    typ = item.get("Type")
                    if typ and _matches_type(typ):
                        work.append(item)
        dbg(f"[JSON] selected={len(work)} only_ip={only_ip or '-'} timeout={timeout}")
        by_type: Dict[str, List[Dict[str, Any]]] = {}
        for it in work:
            t = str(it.get("Type") or "").strip()
            by_type.setdefault(t, []).append(it)
        learned: Dict[str, str] = {}
        for t, items in by_type.items():
            preset = ""
            for it in items:
                pi0 = it.get("printerInfo") or {}
                tt0 = pi0.get("tonerType") or ""
                if tt0:
                    preset = tt0
                    break
            if preset:
                learned[t] = preset
                continue
            rep_ip = None
            rep_id = "-"
            for it in items:
                ip = _norm(it.get("Printer IP"))
                if ip and ip.lower() not in ("-", "null"):
                    rep_ip = ip
                    rep_id = str(it.get("ID") or "-")
                    break
            if not rep_ip:
                _offline_events.append((rep_id, "-", f"no IP for type {t}"))
                learned[t] = ""
                continue
            try:
                tid = _fetch_toner_name(rep_ip, timeout)
                learned[t] = tid or ""
                dbg(f"[TYPE] {t} learned tonerType={learned[t]} from {rep_ip}")
            except Exception as e:
                learned[t] = ""
                _log_warn(f"[OFFLINE] ID='{rep_id}' ip={rep_ip} -> {e}")
                _offline_events.append((rep_id, rep_ip, str(e)))
        for t, items in by_type.items():
            tid = learned.get(t, "")
            for it in items:
                pi = it.setdefault("printerInfo", {})
                if tid:
                    pi["tonerType"] = tid
        touched = len(work)
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
    p = argparse.ArgumentParser(description="Update printers.json with toner type from printer EWS supplies JSON")
    p.add_argument("-ip", dest="only_ip", help='Process only the matching "Printer IP" from printers.json (bypasses TARGET_TYPES)')
    p.add_argument("-t", "--timeout", dest="timeout", type=float, help="Per-printer timeout in seconds (default: 12)")
    p.add_argument("-d", "--debug", dest="debug", type=_str2bool, default=False, help="Debug logging to console: true|false (default: false)")
    p.add_argument("-l", "--log", dest="log", type=_str2bool, default=True, help="Write detailed log file: true|false (default: true)")
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
        toner = pi.get("tonerType") or ""
        reason = pi.get("reason") or ""

        line = f"[ PRINTER {id_} ] {ip} — {status}"
        if toner:
            line += f" — toner: {toner}"
        if reason and status == "offline":
            line += f" — {reason}"
        print(line)

def run() -> int:
    ap = _build_argparser()
    args = ap.parse_args()

    global DEBUG, LOG_ENABLED
    DEBUG = bool(args.debug)
    LOG_ENABLED = bool(args.log)

    logfile = _setup_file_logger()

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
