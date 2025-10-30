
from __future__ import annotations
import argparse, json, logging, re, sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Iterable, Union
import requests
from bs4 import BeautifulSoup
from requests.exceptions import Timeout, RequestException

xxx = "printers.json"
TARGET_TYPES = {"MFC-L9570CDW", "MFC-L6900DW"}
HEADERS = {"User-Agent": "Mozilla/5.0 (+printer-ink-updater)"}
COLOR_PRETTY = {"BK":"Black","K":"Black","C":"Cyan","M":"Magenta","Y":"Yellow"}

def str2bool(v):
    if isinstance(v, bool): return v
    s = str(v).strip().lower()
    if s in {"1","true","t","yes","y","on"}: return True
    if s in {"0","false","f","no","n","off"}: return False
    raise argparse.ArgumentTypeError("expected true/false")

def project_root() -> Path:
    return Path(__file__).resolve().parents[2]

def default_json_path() -> Path:
    return Path(xxx).resolve()

def find_json_path(cli_path: Optional[str]) -> Path:
    return default_json_path()

def load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f: return json.load(f)

def save_json(path: Path, data: Dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

def normalize_label(text: str) -> Optional[str]:
    t = re.sub(r"[^A-Za-z]", "", (text or "")).upper()
    if not t: return None
    if t in {"BK","K","BLK","BLACK"}: return "BK"
    if t in {"C","CYAN"}: return "C"
    if t in {"M","MAGENTA"}: return "M"
    if t in {"Y","YELLOW"}: return "Y"
    return t

def clamp_pct(v: Optional[int]) -> Optional[int]:
    if v is None: return None
    try: return max(0, min(int(v), 100))
    except: return None

def pct_with_symbol(v: Optional[int]) -> Optional[str]:
    vv = clamp_pct(v)
    return None if vv is None else f"{vv}%"

def extract_img_height(td) -> Optional[int]:
    img = td.find("img")
    if img:
        h = img.get("height")
        if h:
            m = re.search(r"\d+", str(h))
            if m: return int(m.group(0))
        style = img.get("style")
        if style:
            m = re.search(r"height\s*:\s*(\d+)", style, re.I)
            if m: return int(m.group(1))
    h = td.get("height")
    if h:
        m = re.search(r"\d+", str(h))
        if m: return int(m.group(0))
    style = td.get("style")
    if style:
        m = re.search(r"height\s*:\s*(\d+)", style, re.I)
        if m: return int(m.group(1))
    return None

def find_level_table(soup: BeautifulSoup):
    table = soup.find("table", id="inkLevel")
    if table: return table
    return soup.find("table", id="inkLevelMono")

def scrape_levels(ip: str, timeout: float, logger: logging.Logger) -> Tuple[str, List[Dict[str, Optional[Union[int,str]]]]]:
    url = f"http://{ip}/general/status.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
    except Timeout:
        logger.debug(f"{ip}: timeout")
        return "offline", []
    except RequestException as e:
        logger.debug(f"{ip}: request error: {e}")
        return "offline", []
    soup = BeautifulSoup(r.text, "html.parser")
    table = find_level_table(soup)
    if not table:
        logger.debug(f"{ip}: ink table not found")
        return "online", []
    tbody = table.find("tbody") or table
    rows = tbody.find_all("tr")
    if len(rows) < 3:
        logger.debug(f"{ip}: unexpected rows {len(rows)}")
        return "online", []
    level_tds = rows[1].find_all("td", recursive=False)
    label_ths = rows[2].find_all("th", recursive=False)
    heights = [extract_img_height(td) for td in level_tds]
    labels = [normalize_label(th.get_text(strip=True)) for th in label_ths]
    labels = [x for x in labels if x]
    cartridges: List[Dict[str, Optional[Union[int,str]]]] = []
    for code, val in zip(labels, heights):
        pretty = COLOR_PRETTY.get(code, code)
        cartridges.append({"cartridge": pretty, "remaining_percent": pct_with_symbol(val)})
    logger.debug(f"{ip}: cartridges parsed: {cartridges}")
    return "online", cartridges

def iter_matching_entries(node: Union[Dict, List]) -> Iterable[Dict]:
    if isinstance(node, dict):
        t = str(node.get("Type","")).strip().upper()
        if t in {s.upper() for s in TARGET_TYPES}: yield node
        for v in node.values(): yield from iter_matching_entries(v)
    elif isinstance(node, list):
        for item in node: yield from iter_matching_entries(item)

def get_ip_from_entry(entry: Dict) -> Optional[str]:
    for k in ("Printer IP","PrinterIP","IP","ip","address"):
        if k in entry and str(entry[k]).strip(): return str(entry[k]).strip()
    return None

def get_id_from_entry(entry: Dict) -> str:
    for k in ("ID","Id","id","_id"):
        if k in entry and str(entry[k]).strip(): return str(entry[k]).strip()
    return "-"

def update_entry_printer_info(entry: Dict, status: str, cartridges: List[Dict[str, Optional[Union[int,str]]]]) -> None:
    entry["printerInfo"] = {"status": status, "cartridges": cartridges}

def setup_logging(enable_log: bool, enable_debug_console: bool) -> Tuple[logging.Logger, Optional[Path]]:
    logger = logging.getLogger("toner")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    log_path = None
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    if enable_log:
        base = project_root() / "logs" / Path(__file__).stem
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_path = base / f"{ts}.log"
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    if enable_debug_console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger, log_path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("-l","--log", type=str2bool, default=True)
    ap.add_argument("-d","--debug", type=str2bool, default=False)
    ap.add_argument("--dry-run", type=str2bool, default=False)
    ap.add_argument("-ip","--ip", dest="only_ip")
    args = ap.parse_args()

    logger, log_path = setup_logging(args.log, args.debug)

    json_path = find_json_path(None)
    if not json_path.exists():
        print(f"printers.json not found at: {json_path}")
        return

    try:
        data = load_json(json_path)
    except Exception as e:
        logger.debug(f"failed to read json: {e}")
        print("failed to read printers.json")
        return

    matched = list(iter_matching_entries(data))
    if args.only_ip:
        matched = [e for e in matched if get_ip_from_entry(e) == args.only_ip]

    if not matched:
        print("No printers with matching Types.")
        return

    processed = online = offline = 0

    for entry in matched:
        ip = get_ip_from_entry(entry)
        if not ip:
            logger.debug("entry missing IP")
            continue
        status, cartridges = scrape_levels(ip, timeout=args.timeout, logger=logger)
        update_entry_printer_info(entry, status, cartridges)

        processed += 1
        if status == "online": online += 1
        else: offline += 1

        if args.debug:
            print(f"{ip} — {status}")
            if cartridges:
                for c in cartridges:
                    pct = c["remaining_percent"]
                    pct_str = "N/A" if pct is None else str(pct)
                    print(f"  - {c['cartridge']}: {pct_str}")
            else:
                print("  (no cartridge data)")
        else:
            pid = get_id_from_entry(entry)
            print(f"[ PRINTER {pid} ] {ip} — {status}")
            if cartridges:
                for c in cartridges:
                    pct = c["remaining_percent"]
                    pct_str = "N/A" if pct is None else str(pct)
                    print(f"  - {c['cartridge']}: {pct_str}")

    if args.dry_run:
        print("dry-run: no file changes")
    else:
        try:
            save_json(json_path, data)
            print(f"Updated: {json_path}")
        except Exception as e:
            logger.debug(f"failed to write json: {e}")
            print("failed to update printers.json")

    if not args.debug:
        print(f"[ SUMMARY ] processed={processed} online={online} offline={offline}")
    elif log_path and args.log and not args.debug:
        print(f"logged to: {log_path}")

if __name__ == "__main__":
    main()
