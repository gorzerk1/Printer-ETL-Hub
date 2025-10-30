from __future__ import annotations
import argparse, json, os, ssl, sys, time, logging, platform
from typing import Dict, Iterable, List, Optional, Tuple, Any
import requests, urllib3
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from xml.etree import ElementTree as ET
from datetime import datetime

TARGET_TYPES = {"M402dn", "M404dn", "M426fdn", "M426fdw", "M477fnw", "M521dn"}
DEFAULT_TIMEOUT = 4.0
PAUSE_BETWEEN_REQS = 0.08

DEBUG = False
LOGGER: Optional[logging.Logger] = None
LOG_ENABLED = False

SEVERITY_ORDER = {
    "CRITICAL": 3, "STRICTERROR": 3, "ERROR": 3,
    "WARNING": 2, "STRICTWARNING": 2,
    "INFO": 1
}

class TLSLegacyAdapter(HTTPAdapter):
    def __init__(self, min_version: Optional["ssl.TLSVersion"] = None,
                 max_version: Optional["ssl.TLSVersion"] = None, **kwargs):
        self._min_version = min_version
        self._max_version = max_version
        super().__init__(**kwargs)
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        if hasattr(ctx, "minimum_version") and hasattr(ssl, "TLSVersion"):
            ctx.minimum_version = self._min_version or ssl.TLSVersion.TLSv1
            ctx.maximum_version = self._max_version or ssl.TLSVersion.TLSv1_2
        self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize,
                                       block=block, ssl_context=ctx, **pool_kwargs)

def _setup_file_logger() -> Optional[str]:
    if not LOG_ENABLED:
        return None
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, ".", "."))
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
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            "%Y-%m-%d %H:%M:%S")
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

def _str2bool(v: str) -> bool:
    s = v.strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError("Boolean value expected (true/false).")

def _cli_debug() -> bool:
    argv = [s.lower() for s in sys.argv]
    if "-d" in argv or "--debug" in argv:
        for a in argv:
            if a.startswith("--debug="):
                val = a.split("=", 1)[1]
                return val in ("1", "true", "t", "yes", "y", "on")
        return True
    return False

def _cli_only_ip() -> Optional[str]:
    ip = None
    argv = sys.argv
    for i, a in enumerate(argv):
        if a in ("-ip", "--ip") and i + 1 < len(argv):
            ip = argv[i + 1]
        elif a.startswith("--ip="):
            ip = a.split("=", 1)[1]
    return ip

def _install_tls_legacy(session: requests.Session) -> None:
    session.mount("https://", TLSLegacyAdapter())

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
    if s in {"critical", "fatal", "stricterror", "error", "severe"}:
        return "critical"
    if s in {"warning", "strictwarning", "warn", "attention"}:
        return "warning"
    if s in {"info", "informational", "notice"}:
        return "informational"
    return "informational"

def _try_get(session: requests.Session, base_host: str, path: str,
             prefer_https: bool, verify_ssl: bool,
             auth: Optional[Tuple[str, str]],
             timeout: float = DEFAULT_TIMEOUT) -> Tuple[Optional[bytes], str]:
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    schemes = ["https", "http"] if prefer_https else ["http", "https"]
    last_err: Optional[str] = None
    for sch in schemes:
        url = f"{sch}://{base_host}{path}"
        try:
            r = session.get(
                url, timeout=timeout, verify=verify_ssl, auth=auth,
                headers={
                    "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.5",
                    "User-Agent": "hp-ledm-json/1.7"
                }
            )
            if r.status_code == 200 and r.content:
                ct = r.headers.get("Content-Type", "").lower()
                if b"<html" in r.content[:200].lower() or "text/html" in ct:
                    last_err = f"{url} -> HTML"
                else:
                    return r.content, url
            else:
                last_err = f"{url} -> HTTP {r.status_code}"
        except requests.exceptions.SSLError as e:
            last_err = f"{url} -> {e}"
            if sch == "https":
                _install_tls_legacy(session)
                try:
                    r = session.get(url, timeout=timeout, verify=verify_ssl, auth=auth)
                    if r.status_code == 200 and r.content:
                        ct = r.headers.get("Content-Type", "").lower()
                        if b"<html" in r.content[:200].lower() or "text/html" in ct:
                            last_err = f"{url} -> HTML"
                        else:
                            return r.content, f"{url} [TLS-legacy]"
                    else:
                        last_err = f"{url} -> HTTP {r.status_code}"
                except Exception as e2:
                    last_err = f"{url} -> {e2}"
        except Exception as e:
            last_err = f"{url} -> {e}"
        time.sleep(0.03)
    return None, (last_err or "fetch failed")

def _parse_xml(xml_bytes: Optional[bytes]) -> Optional[ET.Element]:
    if not xml_bytes:
        return None
    try:
        return ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

def _lname(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag

def iter_elems_by_local(root: Optional[ET.Element], local_names: Iterable[str]) -> List[ET.Element]:
    if root is None:
        return []
    wanted = set(local_names)
    out: List[ET.Element] = []
    for el in root.iter():
        try:
            if _lname(el.tag) in wanted:
                out.append(el)
        except Exception:
            pass
    return out

def text_of_first(root: Optional[ET.Element], candidates: Iterable[str]) -> Optional[str]:
    if root is None:
        return None
    wanted = set(candidates)
    for el in root.iter():
        if _lname(getattr(el, "tag", "")) in wanted:
            txt = (el.text or "").strip()
            if txt:
                return txt
    return None

def best_event_from_table(event_root: Optional[ET.Element]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if event_root is None:
        return (None, None, None)
    best = None
    best_rank = -1
    for ev in iter_elems_by_local(event_root, ["Event"]):
        sev_raw = (text_of_first(ev, ["Severity"]) or "").strip().upper()
        rank = SEVERITY_ORDER.get(sev_raw, -1)
        if rank >= best_rank:
            code = (text_of_first(ev, ["Code", "EventCode", "ID", "ErrorCode"]) or "").strip()
            desc = (text_of_first(ev, ["Description", "EventDescription", "Name", "Reason"]) or "").strip()
            best = (code if code else None, desc if desc else None, _triage_three(sev_raw))
            best_rank = rank
    return best if best else (None, None, None)

def problem_from_status(status_root: Optional[ET.Element]) -> Optional[str]:
    s = text_of_first(status_root, ["LocString","StatusString","StatusMessage","Reason","DetailedReason","State"])
    if s:
        return s
    cat = (text_of_first(status_root, ["StatusCategory"]) or "").strip().lower()
    if cat:
        mapping = {
            "ready": "Ready", "processing": "Processing", "warmup": "Warming up",
            "attention": "Needs attention", "interventionrequired": "Needs attention",
            "error": "Error", "idle": "Idle", "sleep": "Sleep"
        }
        return mapping.get(cat, cat.capitalize())
    return None

def derive_severity_from_problem(problem: Optional[str]) -> str:
    if not problem:
        return "informational"
    p = problem.lower()
    if any(k in p for k in ["jam", "door", "open", "cover", "fault", "failure", "error", "empty", "replace"]):
        return "critical"
    if any(k in p for k in ["low", "depleted", "almost", "calibrat", "warming", "busy", "sleep", "power saver", "attention"]):
        return "warning"
    return "informational"

def _best_alert_from_status(status_root: Optional[ET.Element]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if status_root is None:
        return (None, None, None)
    alerts = iter_elems_by_local(status_root, ["Alert"])
    if not alerts:
        return (None, None, None)
    sev_rank = {"CRITICAL":3,"ERROR":3,"WARNING":2,"INFO":1,"STRICTERROR":3,"STRICTWARNING":2}
    best = None
    best_score = -1
    for a in alerts:
        sev_raw = (text_of_first(a, ["Severity"]) or "Info").strip().upper()
        code = (text_of_first(a, ["ProductStatusAlertID","StringId","ID","Code"]) or "").strip()
        desc = (text_of_first(a, ["AlertDetailsUserAction","Description","Name","Reason"]) or "").strip()
        score = sev_rank.get(sev_raw, 0)
        if score >= best_score:
            best = (code if code else None, desc if desc else None, _triage_three(sev_raw))
            best_score = score
    return best if best else (None, None, None)

def process_printer(ip: str, session: requests.Session,
                    prefer_https: bool, verify_ssl: bool,
                    auth: Optional[Tuple[str, str]]) -> Tuple[str, str]:
    dbg(f"[HTTP] host={ip} https={bool(prefer_https)} verify_ssl={bool(verify_ssl)} auth={'on' if auth else 'off'}")
    paths = {"status": "/DevMgmt/ProductStatusDyn.xml", "events": "/EventMgmt/EventTable.xml"}
    raw: Dict[str, Optional[bytes]] = {}
    for key, pth in paths.items():
        content, url_or_err = _try_get(session, ip, pth, prefer_https, verify_ssl, auth, timeout=DEFAULT_TIMEOUT)
        if content is None:
            dbg(f"[HTTP] {key} -> {url_or_err}")
        else:
            dbg(f"[HTTP] {key} <- {url_or_err}")
        raw[key] = content
        time.sleep(PAUSE_BETWEEN_REQS)
    status_root = _parse_xml(raw.get("status"))
    events_root = _parse_xml(raw.get("events"))
    _ev_code, ev_problem, ev_sev = best_event_from_table(events_root)
    st_problem = problem_from_status(status_root)
    _al_code, al_problem, al_sev = _best_alert_from_status(status_root)
    problem = ev_problem or al_problem or st_problem or "Unknown"
    severity = ev_sev or al_sev or derive_severity_from_problem(problem)
    dbg(f"[PRINTER] {ip} problem='{problem}' severity='{severity}'")
    return problem, severity

def _normalize_problem_and_severity(problem: Optional[str],
                                    severity: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    p = (problem or "").strip()
    low = p.lower()
    if "unknown" in low:
        return (None, "informational")
    if "acknowledgeconsumablestate" in low:
        return ("Ready", "informational")
    if ("ready" in low and "not ready" not in low and "unready" not in low) or ("מוכן" in p):
        return ("Ready", "informational")
    if ("sleep" in low) or ("inpowersave" in low) or ("שינה" in p):
        return ("Sleeping", "informational")
    return (problem, severity)

def _status_from_entry(entry: Dict[str, Any]) -> str:
    try:
        info = entry.get("printerInfo") or {}
        err = info.get("printerError") or {}
        s = str(err.get("problem") or "").lower()
        return "offline" if s.startswith("unreachable") else "online"
    except Exception:
        return "offline"

def _collect_entry_refs(data: Any) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        for key in ("Company_Grouped", "Branches_Grouped", "printers"):
            if isinstance(data.get(key), list):
                for e in data[key]:
                    if isinstance(e, dict):
                        entries.append(e)
        if not entries:
            for v in data.values():
                if isinstance(v, dict) and ("Type" in v or "Printer IP" in v):
                    entries.append(v)
    elif isinstance(data, list):
        entries = [e for e in data if isinstance(e, dict)]
    return entries

def _filter_targets(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    wanted = {t.lower() for t in TARGET_TYPES}
    out: List[Dict[str, Any]] = []
    for e in entries:
        t = str(e.get("Type", "")).strip().lower()
        ip = str(e.get("Printer IP", "")).strip()
        if t in wanted and ip and ip != "-":
            out.append(e)
    return out

def _print_unified_console_from_file(path: str, only_ip: Optional[str]) -> None:
    if _cli_debug():
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return
    entries = _collect_entry_refs(data)
    processed = online = offline = 0
    for e in entries:
        ip = str(e.get("Printer IP") or "-")
        if only_ip and str(ip).strip() != str(only_ip).strip():
            continue
        if "printerInfo" in e and isinstance(e["printerInfo"], dict):
            status_state = _status_from_entry(e)
            processed += 1
            if status_state == "online":
                online += 1
            else:
                offline += 1
            print(f"[ PRINTER ] {ip} — {status_state}")
    if processed:
        print(f"[ SUMMARY ] processed={processed} online={online} offline={offline}")

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Poll HP LEDM and update printers.json in-place at printerInfo.printerError.{problem,severity}"
    )
    p.add_argument("-i", "--input", dest="input", default="printers.json")
    p.add_argument("--https", action="store_true")
    p.add_argument("--verify-ssl", action="store_true")
    p.add_argument("--user", default="")
    p.add_argument("--password", default="")
    p.add_argument("-ip", "--ip", dest="only_ip")
    p.add_argument("-d", "--debug", dest="debug", type=_str2bool, default=False, help="true|false")
    p.add_argument("-l", "--log", dest="log", type=_str2bool, default=True, help="true|false")
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
    input_path = args.input
    if input_path == "printers.json":
        input_path = os.path.join(os.getcwd(), "printers.json")
    try:
        with open(input_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        return 2
    except Exception as ex:
        print(f"ERROR: failed to read JSON: {ex}", file=sys.stderr)
        return 2
    entries = _collect_entry_refs(data)
    targets = _filter_targets(entries)
    only_ip = (args.only_ip or "").strip() or None
    if only_ip:
        targets = [e for e in targets if str(e.get("Printer IP", "")).strip() == only_ip]
        dbg(f"[JSON] selected={len(targets)} only_ip={only_ip} timeout=None")
    else:
        dbg(f"[JSON] selected={len(targets)}")
    session = requests.Session()
    auth = (args.user, args.password) if (args.user or args.password) else None
    prefer_https = args.https
    verify_ssl = args.verify_ssl
    processed = online = 0
    offline_pairs: List[Tuple[str, str]] = []
    for e in targets:
        ip = str(e.get("Printer IP", "")).strip()
        if not ip or ip == "-":
            continue
        label = e.get("ID") or e.get("Name") or e.get("Branch") or e.get("Site") or ip
        dbg(f"[MATCH] enriching '{label}' ip={ip}")
        try:
            problem, severity = process_printer(ip, session, prefer_https, verify_ssl, auth)
        except Exception as ex:
            offline_pairs.append((ip, str(ex)))
            problem, severity = (f"Unreachable: {ex}", "informational")
        problem, severity = _normalize_problem_and_severity(problem, severity)
        if not isinstance(e.get("printerInfo"), dict):
            e["printerInfo"] = {}
        if not severity:
            severity = "informational"
        pe = {
            "problem":  problem,
            "severity": severity
        }
        if ((problem or "").strip().lower() == "ready"):
            pe["acknowledgeConsumableState"] = "Ready"
        e["printerInfo"]["printerError"] = pe
        processed += 1
        if not str(problem or "").lower().startswith("unreachable"):
            online += 1
    try:
        with open(input_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        dbg(f"[JSON] updated {os.path.abspath(input_path)}; processed={processed}")
    except Exception as ex:
        print(f"ERROR: failed to write updated JSON: {ex}", file=sys.stderr)
        return 3
    _print_unified_console_from_file(input_path, only_ip)
    if _cli_debug():
        print(f"[SUMMARY] processed={processed} online={online} offline={len(offline_pairs)}")
    _log_info("")
    _log_info(f"Summary: processed={processed} online={online} offline={len(offline_pairs)}")
    for ip, reason in offline_pairs:
        _log_warn(f"[OFFLINE] {ip} -> {reason}")
    if logfile:
        _log_info(f"Log saved to: {logfile}")
    _log_info("=== run end ===")
    return 0

if __name__ == "__main__":
    rc = run()
    raise SystemExit(rc)
