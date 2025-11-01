# adapters/ews_alerts.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import json, re
import requests
import urllib3
from bs4 import BeautifulSoup
from adapters.http_legacy import make_legacy_session

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CODE_RE = re.compile(r"\b[A-Z]\d-\d{3,5}\b")

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
    s = s.lower()
    if s in {"critical", "fatal", "severe", "error"}:
        return "critical"
    if s in {"attention", "warning", "warn"}:
        return "warning"
    if s in {"info", "informational", "notice"}:
        return "informational"
    return "informational"

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

def _load_code_catalog(path: Optional[str]) -> Dict[str, Dict[str, str]]:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    mapping: Dict[str, Dict[str, str]] = {}
    def _add_item(code: str, status: str, info: str):
        code = (code or "").strip()
        if code:
            mapping[code] = {"status": (status or "").strip().upper() or "INFO", "info": (info or "").strip()}
    items = raw
    if isinstance(raw, dict) and "items" in raw and isinstance(raw["items"], list):
        items = raw["items"]
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                _add_item(it.get("code",""), it.get("status",""), it.get("info",""))
    elif isinstance(items, dict):
        for code, val in items.items():
            if isinstance(val, dict):
                _add_item(code, val.get("status",""), val.get("info",""))
    return mapping

def _severity_rank(sev: str) -> int:
    if sev is None:
        return 0
    s = str(sev).strip()
    if s.isdigit():
        return int(s)
    s = s.lower()
    if s in ("fatal","critical"):
        return 9
    if s in ("error","severe"):
        return 6
    if s in ("warning",):
        return 3
    if s == "attention":
        return 5
    if s in ("info","informational"):
        return 1
    return 0

def _catalog_status_to_rank(status: Optional[str]) -> int:
    s = (status or "").strip().upper()
    if s == "CRITICAL":
        return 9
    if s == "ATTENTION":
        return 5
    if s == "INFO":
        return 1
    return 0

def _short_label_for(code: str, desc: str, catalog: Dict[str, Dict[str, str]]) -> Tuple[str, Optional[str]]:
    if code and code in catalog:
        entry = catalog[code]
        return (entry.get("info") or "Check printer", entry.get("status") or None)
    d = (desc or "").strip().lower()
    if not d:
        return ("Normal", None)
    if "door" in d:
        return ("Door open", None)
    if "jam" in d:
        return ("Paper jam", None)
    if "toner" in d and "detect" in d:
        return ("Toner not detected", None)
    if "toner" in d and ("empty" in d or "end" in d):
        return ("Toner empty", None)
    if ("drum" in d) or ("imaging unit" in d):
        if "not" in d and "install" in d:
            return ("Drum not installed", None)
        if "end" in d or "replace" in d:
            return ("Replace drum now", None)
    if "transfer" in d:
        return ("Transfer roller fault", None)
    if "scanner" in d:
        return ("Scanner error", None)
    if "fuser" in d:
        return ("Fuser error", None)
    return ("Check printer", None)

def _normalize_problem_and_severity(problem: str) -> Tuple[str, Optional[str]]:
    p = (problem or "").strip()
    low = p.lower()
    if p == "" or low == "normal":
        return ("Ready", "informational")
    if "sleep" in low:
        return ("Sleeping", "informational")
    return (p, None)

def _session_probe_get(s: requests.Session, url: str, timeout: float) -> Optional[str]:
    try:
        r = s.get(url, verify=False, timeout=timeout)
    except Exception:
        return None
    if r.status_code != 200 or not r.text:
        return None
    if "html" not in (r.headers.get("content-type","")).lower():
        if not r.encoding:
            r.encoding = r.apparent_encoding
        return r.text
    return r.text

def _fetch_ews_alerts(ip: str, timeout: float) -> List[Dict[str, str]]:
    s = make_legacy_session(timeout=timeout)
    out: List[Dict[str, str]] = []
    for scheme in ("https", "http"):
        base = f"{scheme}://{ip}"
        try:
            s.get(f"{base}/sws/index.html", verify=False, timeout=timeout)
        except Exception:
            pass
        for path in (
            "/sws/app/information/activealert/activealert.json",
            "/sws/app/information/activealert/activeAlert.json",
            "/sws/app/information/activealert/active_alert.json",
            "/sws/app/information/activealert/alert.json",
        ):
            txt = _session_probe_get(s, base + path, timeout)
            if txt and "{" in txt:
                try:
                    data = _parse_json_text(txt)
                    alerts = _extract_alerts_from_json(data)
                    if alerts:
                        return alerts
                except Exception:
                    pass
        try:
            r = s.get(f"{base}/sws/app/information/activealert/activealert.html", verify=False, timeout=timeout)
            if r.status_code == 200:
                if not r.encoding:
                    r.encoding = r.apparent_encoding
                alerts = _extract_alerts_from_html(r.text)
                if alerts:
                    return alerts
        except Exception:
            pass
    return out

def _pick_alert(alerts: List[Dict[str, str]], catalog: Dict[str, Dict[str, str]]) -> Tuple[str, str, str]:
    if not alerts:
        return ("", "", "informational")
    def rank(a: Dict[str, str]) -> Tuple[int, int]:
        r = _severity_rank(a.get("severity",""))
        if r == 0:
            code = a.get("status_code","")
            if code and code in catalog:
                r = _catalog_status_to_rank(catalog[code].get("status"))
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
    if code and code in catalog:
        base_sev = _triage_three(catalog[code].get("status"))
    if not base_sev:
        base_sev = _triage_three(top.get("severity"))
    return (code, desc, base_sev)

def get_ews_problem_and_severity(ip: str, *, timeout: float, catalog_path: Optional[str]) -> Tuple[str, str]:
    alerts = _fetch_ews_alerts(ip, timeout)
    catalog = _load_code_catalog(catalog_path)
    code, desc, base_sev = _pick_alert(alerts, catalog)
    label, sev_from_catalog = _short_label_for(code, desc, catalog)
    label, forced = _normalize_problem_and_severity(label)
    sev = forced or (_triage_three(sev_from_catalog) if sev_from_catalog else base_sev)
    return label or "Ready", sev or "informational"
