# adapters/brother_toner_web.py
from __future__ import annotations
import re
from typing import Dict, List, Optional, Tuple
import requests
from bs4 import BeautifulSoup
from requests.exceptions import Timeout, RequestException

HEADERS = {"User-Agent": "Mozilla/5.0 (+toner-finder)"}
COLOR_PRETTY = {"BK": "Black", "K": "Black", "C": "Cyan", "M": "Magenta", "Y": "Yellow"}

def _normalize_label(text: str) -> Optional[str]:
    t = re.sub(r"[^A-Za-z]", "", (text or "")).upper()
    if not t:
        return None
    if t in {"BK", "K", "BLK", "BLACK"}:
        return "BK"
    if t in {"C", "CYAN"}:
        return "C"
    if t in {"M", "MAGENTA"}:
        return "M"
    if t in {"Y", "YELLOW"}:
        return "Y"
    return t

def _clamp_pct(v: Optional[int]) -> Optional[int]:
    if v is None:
        return None
    try:
        return max(0, min(int(v), 100))
    except Exception:
        return None

def _pct_with_symbol(v: Optional[int]) -> Optional[str]:
    vv = _clamp_pct(v)
    return None if vv is None else f"{vv}%"

def _extract_img_height(td) -> Optional[int]:
    img = td.find("img")
    if img:
        h = img.get("height")
        if h:
            m = re.search(r"\d+", str(h))
            if m:
                return int(m.group(0))
        style = img.get("style")
        if style:
            m = re.search(r"height\s*:\s*(\d+)", style, re.I)
            if m:
                return int(m.group(1))
    h = td.get("height")
    if h:
        m = re.search(r"\d+", str(h))
        if m:
            return int(m.group(0))
    style = td.get("style")
    if style:
        m = re.search(r"height\s*:\s*(\d+)", style, re.I)
        if m:
            return int(m.group(1))
    return None

def _find_level_table(soup: BeautifulSoup):
    table = soup.find("table", id="inkLevel")
    if table:
        return table
    return soup.find("table", id="inkLevelMono")

def get_brother_toner(ip: str, *, timeout: float) -> Tuple[str, List[Dict[str, Optional[str]]]]:
    url = f"http://{ip}/general/status.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
    except Timeout:
        return "offline", []
    except RequestException:
        return "offline", []
    soup = BeautifulSoup(r.text, "html.parser")
    table = _find_level_table(soup)
    if not table:
        return "online", []
    tbody = table.find("tbody") or table
    rows = tbody.find_all("tr")
    if len(rows) < 3:
        return "online", []
    level_tds = rows[1].find_all("td", recursive=False)
    label_ths = rows[2].find_all("th", recursive=False)
    heights = [_extract_img_height(td) for td in level_tds]
    labels = [_normalize_label(th.get_text(strip=True)) for th in label_ths]
    labels = [x for x in labels if x]
    cartridges: List[Dict[str, Optional[str]]] = []
    for code, val in zip(labels, heights):
        pretty = COLOR_PRETTY.get(code, code)
        cartridges.append({"cartridge": pretty, "remaining_percent": _pct_with_symbol(val)})
    return "online", cartridges
