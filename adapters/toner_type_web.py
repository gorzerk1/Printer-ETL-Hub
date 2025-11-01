# adapters/toner_type_web.py
from __future__ import annotations
import json, re
from typing import Any, Optional
from bs4 import BeautifulSoup
from adapters.http_legacy import make_legacy_session

_TONER_PATTERNS = [r"W\d{4}[A-Z](?:X)?", r"MLT-[A-Z]\d{3,5}[A-Z]*", r"[A-Z]{2}\d{3}[A-Z]"]
TONER_ID_RE = re.compile(r"(?:%s)" % "|".join(_TONER_PATTERNS))
SUPPLIES_PATHS = (
    "/sws/app/information/supplies/supplies.json",
    "/sws/app/information/supplies/supply.json",
    "/sws/app/information/home/home.json",
)

def _parse_json_text(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        try:
            import json5  # type: ignore
            return json5.loads(text)
        except Exception:
            pass
    fixed = re.sub(r'([{\[,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*):', r'\1"\2"\3:', text)
    return json.loads(fixed)

def _extract_toner_from_supplies_json(obj: Any) -> str:
    candidates = []
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

def get_ews_toner_type(ip: str, *, timeout: Optional[float]) -> str:
    s = make_legacy_session(timeout=timeout or 12.0)
    for scheme in ("https://", "http://"):
        base = f"{scheme}{ip}"
        try:
            s.get(f"{base}/sws/index.html", verify=False, timeout=timeout or 12.0)
        except Exception:
            pass
        for path in SUPPLIES_PATHS:
            try:
                r = s.get(base + path, verify=False, timeout=timeout or 12.0)
                if r.status_code == 200 and r.text and ("{" in r.text or "[" in r.text):
                    try:
                        data = _parse_json_text(r.text)
                    except Exception:
                        data = None
                    if data is not None:
                        tid = _extract_toner_from_supplies_json(data)
                        if tid:
                            return tid
                    m = TONER_ID_RE.search(r.text)
                    if m:
                        return m.group(0)
            except Exception:
                continue
        for html_path in ("/sws/app/information/supplies/supplies.html",
                          "/sws/app/information/status/supplies.html",
                          "/sws/index.html"):
            try:
                r = s.get(base + html_path, verify=False, timeout=timeout or 12.0)
                if r.status_code == 200 and r.text:
                    tid = _extract_toner_from_html(r.text)
                    if tid:
                        return tid
            except Exception:
                continue
    return ""
