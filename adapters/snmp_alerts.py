# adapters/snmp_alerts.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from adapters.snmp_client import walk_oid

ALERT_TABLE_ROOT = "1.3.6.1.2.1.43.18.1.1"
COL_SEVERITY = "2"
COL_TRAINING = "3"
COL_GROUP = "4"
COL_GROUPIDX = "5"
COL_LOCATION = "6"
COL_CODE = "7"
COL_DESC = "8"
COL_TIME = "9"

HR_PRN_ERRORSTATE_BASE = "1.3.6.1.2.1.25.3.5.1.2"

HR_BITS = [
    ("lowPaper", 0),
    ("noPaper", 1),
    ("lowToner", 2),
    ("noToner", 3),
    ("doorOpen", 4),
    ("jammed", 5),
    ("offline", 6),
    ("serviceRequested", 7),
    ("inputTrayMissing", 8),
    ("outputTrayMissing", 9),
    ("markerSupplyMissing", 10),
    ("outputNearFull", 11),
    ("outputFull", 12),
    ("inputTrayEmpty", 13),
    ("overduePreventMaint", 14),
]

SUPPRESS_PHRASES = {
    "sleep mode on",
    "power saver mode",
    "מצב שינה פועל",
    "genuine hp cartridge installed",
}

HEB_EN = {
    "תוף שחור ברמה נמוכה מאוד": "Black drum very low",
    "אי-התאמת גודל ב-מגש 1": "Tray 1 size mismatch",
    "גודל בלתי צפוי ב-מגש 1": "Unexpected size in Tray 1",
    "מושהה": "Paused",
    "41.03.B1 גודל בלתי צפוי ב-מגש 1": "Unexpected size in Tray 1",
    "66044": "Service requested",
}

def _to_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v)

def _severity_tag(num: Optional[int]) -> str:
    if num is None:
        return "unknown"
    try:
        n = int(num)
    except Exception:
        return "unknown"
    if n == 1:
        return "other"
    if n == 2:
        return "unknown"
    if n == 3:
        return "warning"
    if n == 4:
        return "critical"
    return "unknown"

def _clean_desc(desc: str) -> str:
    d = (desc or "").strip()
    if not d:
        return ""
    if d in HEB_EN:
        d = HEB_EN[d]
    if d.lower() in SUPPRESS_PHRASES:
        return ""
    return d

def _mk_msg(severity: str, group: Optional[int], code: Optional[int], desc: Optional[str], groupidx: Optional[int]) -> str:
    d = _clean_desc(desc or "")
    if d:
        return d
    if code:
        return f"Code {code}"
    return ""

def _hr_bits_as_flags(bits: int) -> List[str]:
    out: List[str] = []
    for name, bitpos in HR_BITS:
        if bits & (1 << bitpos):
            out.append(name)
    return out

def _snmp_alert_rows(ip: str, community: str, timeout: Optional[float]) -> Dict[int, Dict[str, Any]]:
    rows: Dict[int, Dict[str, Any]] = {}
    for oid, value in walk_oid(ip, ALERT_TABLE_ROOT, community=community, timeout=timeout):
        parts = oid.split(".")
        if len(parts) < 2:
            continue
        col = parts[-2]
        row = int(parts[-1])
        rowdict = rows.setdefault(row, {})
        if col == COL_SEVERITY:
            try:
                rowdict[COL_SEVERITY] = int(value)
            except Exception:
                pass
        elif col == COL_GROUP:
            try:
                rowdict[COL_GROUP] = int(value)
            except Exception:
                pass
        elif col == COL_GROUPIDX:
            try:
                rowdict[COL_GROUPIDX] = int(value)
            except Exception:
                pass
        elif col == COL_CODE:
            try:
                rowdict[COL_CODE] = int(value)
            except Exception:
                pass
        elif col == COL_DESC:
            txt = _to_text(value).strip()
            if txt:
                rowdict[COL_DESC] = txt
        elif col == COL_TIME:
            rowdict[COL_TIME] = _to_text(value).strip()
    return rows

def _snmp_hr_errorstate(ip: str, community: str, timeout: Optional[float]) -> Optional[Tuple[str, str]]:
    for oid, value in walk_oid(ip, HR_PRN_ERRORSTATE_BASE, community=community, timeout=timeout):
        try:
            bits = int(value)
        except Exception:
            continue
        flags = _hr_bits_as_flags(bits)
        if not flags:
            return None
        msg = ", ".join(flags)
        sev = "warning"
        if "offline" in flags or "serviceRequested" in flags:
            sev = "critical"
        return msg, sev
    return None

def _decide_message_from_rows(rows: Dict[int, Dict[str, Any]]) -> Optional[Tuple[str, str]]:
    if not rows:
        return None
    ordered = sorted(rows.items(), key=lambda t: t[0])
    chosen_msg: Optional[str] = None
    chosen_tag: Optional[str] = None
    for severity_pick in ("critical", "warning", "other", "unknown"):
        for _, r in ordered:
            tag = _severity_tag(r.get(COL_SEVERITY))
            if tag != severity_pick:
                continue
            msg = _mk_msg(
                severity_pick,
                r.get(COL_GROUP),
                r.get(COL_CODE),
                r.get(COL_DESC),
                r.get(COL_GROUPIDX),
            )
            if msg:
                chosen_msg = msg
                chosen_tag = severity_pick
                break
        if chosen_msg:
            break
    if not chosen_msg:
        return None
    final_sev = "critical" if chosen_tag == "critical" else "warning"
    return chosen_msg, final_sev

def process_snmp_alerts(ip: str, *, community: str, timeout: Optional[float]) -> Tuple[str, str]:
    rows = _snmp_alert_rows(ip, community, timeout)
    if rows:
        decided = _decide_message_from_rows(rows)
        if decided:
            return decided
    hr = _snmp_hr_errorstate(ip, community, timeout)
    if hr:
        return hr
    return "Normal", "informational"
