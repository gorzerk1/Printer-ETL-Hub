# adapters/ledm_client.py
from __future__ import annotations
import time
from typing import Iterable, List, Optional, Tuple
import requests
import urllib3
from xml.etree import ElementTree as ET
from adapters.http_legacy import make_legacy_session

SEVERITY_ORDER = {
    "CRITICAL": 3,
    "STRICTERROR": 3,
    "ERROR": 3,
    "WARNING": 2,
    "STRICTWARNING": 2,
    "INFO": 1,
}

def _lname(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag

def _iter_elems_by_local(root: Optional[ET.Element], local_names: Iterable[str]) -> List[ET.Element]:
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

def _text_of_first(root: Optional[ET.Element], candidates: Iterable[str]) -> Optional[str]:
    if root is None:
        return None
    wanted = set(candidates)
    for el in root.iter():
        if _lname(getattr(el, "tag", "")) in wanted:
            txt = (el.text or "").strip()
            if txt:
                return txt
    return None

def _triage_three(sev: Optional[str]) -> str:
    if sev is None:
        return "informational"
    s = str(sev).strip()
    if s.isdigit():
        n = int(s)
        if n >= 6:
            return "critical"
        if n >= 3:
            return "warning"
        return "informational"
    low = s.lower()
    if low in {"critical", "fatal", "stricterror", "error", "severe"}:
        return "critical"
    if low in {"warning", "strictwarning", "warn", "attention"}:
        return "warning"
    if low in {"info", "informational", "notice"}:
        return "informational"
    return "informational"

def _parse_xml(xml_bytes: Optional[bytes]) -> Optional[ET.Element]:
    if not xml_bytes:
        return None
    try:
        return ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

def _try_get(session: requests.Session, host: str, path: str, *, timeout: float, verify_ssl: bool = False) -> Optional[bytes]:
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    for scheme in ("https", "http"):
        url = f"{scheme}://{host}{path}"
        try:
            r = session.get(url, timeout=timeout, verify=verify_ssl, headers={"Accept": "application/xml,text/xml;q=0.9,*/*;q=0.5"})
            if r.status_code == 200 and r.content and b"<html" not in r.content[:200].lower():
                return r.content
        except Exception:
            pass
        time.sleep(0.03)
    return None

def fetch_ledm_roots(ip: str, *, timeout: float, pause_between_reqs: float = 0.08) -> Tuple[Optional[ET.Element], Optional[ET.Element]]:
    s = make_legacy_session(timeout=timeout)
    status = _try_get(s, ip, "/DevMgmt/ProductStatusDyn.xml", timeout=timeout, verify_ssl=False)
    events = _try_get(s, ip, "/EventMgmt/EventTable.xml", timeout=timeout, verify_ssl=False)
    if pause_between_reqs:
        time.sleep(pause_between_reqs)
    return _parse_xml(status), _parse_xml(events)

def best_event_from_table(event_root: Optional[ET.Element]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if event_root is None:
        return (None, None, None)
    best = None
    best_rank = -1
    for ev in _iter_elems_by_local(event_root, ["Event"]):
        sev_raw = (_text_of_first(ev, ["Severity"]) or "").strip().upper()
        rank = SEVERITY_ORDER.get(sev_raw, -1)
        if rank >= best_rank:
            code = (_text_of_first(ev, ["Code", "EventCode", "ID", "ErrorCode"]) or "").strip()
            desc = (_text_of_first(ev, ["Description", "EventDescription", "Name", "Reason"]) or "").strip()
            best = (code if code else None, desc if desc else None, _triage_three(sev_raw))
            best_rank = rank
    return best if best else (None, None, None)

def problem_from_status(status_root: Optional[ET.Element]) -> Optional[str]:
    s = _text_of_first(status_root, ["LocString", "StatusString", "StatusMessage", "Reason", "DetailedReason", "State"])
    if s:
        return s
    cat = (_text_of_first(status_root, ["StatusCategory"]) or "").strip().lower()
    if cat:
        mapping = {
            "ready": "Ready",
            "processing": "Processing",
            "warmup": "Warming up",
            "attention": "Needs attention",
            "interventionrequired": "Needs attention",
            "error": "Error",
            "idle": "Idle",
            "sleep": "Sleep",
        }
        return mapping.get(cat, cat.capitalize())
    return None

def _best_alert_from_status(status_root: Optional[ET.Element]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if status_root is None:
        return (None, None, None)
    alerts = _iter_elems_by_local(status_root, ["Alert"])
    if not alerts:
        return (None, None, None)
    sev_rank = {"CRITICAL": 3, "ERROR": 3, "WARNING": 2, "INFO": 1, "STRICTERROR": 3, "STRICTWARNING": 2}
    best = None
    best_score = -1
    for a in alerts:
        sev_raw = (_text_of_first(a, ["Severity"]) or "Info").strip().upper()
        code = (_text_of_first(a, ["ProductStatusAlertID", "StringId", "ID", "Code"]) or "").strip()
        desc = (_text_of_first(a, ["AlertDetailsUserAction", "Description", "Name", "Reason"]) or "").strip()
        score = sev_rank.get(sev_raw, 0)
        if score >= best_score:
            best = (code if code else None, desc if desc else None, _triage_three(sev_raw))
            best_score = score
    return best if best else (None, None, None)

def derive_severity_from_problem(problem: Optional[str]) -> str:
    if not problem:
        return "informational"
    p = problem.lower()
    if any(k in p for k in ["jam", "door", "open", "cover", "fault", "failure", "error", "empty", "replace"]):
        return "critical"
    if any(k in p for k in ["low", "depleted", "almost", "calibrat", "warming", "busy", "sleep", "power saver", "attention"]):
        return "warning"
    return "informational"

def normalize_problem_and_severity(problem: Optional[str], severity: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
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

def get_ledm_problem_and_severity(ip: str, *, timeout: float) -> Tuple[str, str]:
    status_root, events_root = fetch_ledm_roots(ip, timeout=timeout)
    _ev_code, ev_problem, ev_sev = best_event_from_table(events_root)
    st_problem = problem_from_status(status_root)
    _al_code, al_problem, al_sev = _best_alert_from_status(status_root)
    problem = ev_problem or al_problem or st_problem or "Unknown"
    severity = ev_sev or al_sev or derive_severity_from_problem(problem)
    problem, severity = normalize_problem_and_severity(problem, severity)
    if not severity:
        severity = "informational"
    return problem or "Normal", severity
