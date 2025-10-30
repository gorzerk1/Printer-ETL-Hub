from __future__ import annotations
import argparse, importlib, inspect, json, os, sys, tempfile, time
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

PRINTERS_JSON_PATH = BASE_DIR / "printers.json"
PLUGIN_ALIASES = {
    "tech":       "plugins.openticket.PrinterTechnician",
    "toner":      "plugins.openticket.TonerOrder",
    "drum":       "plugins.openticket.DrumOrder"
}

def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _require_json(initial: str | None) -> Dict[str, Any]:
    p = Path(initial) if initial else PRINTERS_JSON_PATH
    if not p.exists():
        while True:
            entered = input("Enter path to printers.json: ").strip().strip('"').strip("'")
            if not entered:
                print("Path required. Try again.")
                continue
            p = Path(entered)
            if p.exists():
                break
            print("File not found. Try again.")
    return _load_json(p)

def _choose(items: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    print("\nMultiple matches found:")
    for i, e in enumerate(items, 1):
        print(f"{i}. ID={e.get('ID','')}  Name={e.get('Name','')}  Serial={e.get('Serial','')}  Printer IP={e.get('Printer IP','')}  Type={e.get('Type','')}")
    while True:
        s = input("Pick a number or leave empty to cancel: ").strip()
        if not s:
            return None
        if s.isdigit():
            i = int(s)
            if 1 <= i <= len(items):
                return items[i-1]

def _try_outlook_com(to_addr: str, subject: str, html_content: str) -> bool:
    try:
        import win32com.client as win32
        try:
            outlook = win32.gencache.EnsureDispatch("Outlook.Application")
        except Exception:
            outlook = win32.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.To = to_addr
        mail.Subject = subject
        mail.BodyFormat = 2
        mail.HTMLBody = html_content
        mail.Display(False)
        return True
    except Exception:
        return False

def _open_eml_draft(to_addr: str, subject: str, html_content: str) -> str:
    path = Path(tempfile.gettempdir()) / f"ticket_draft_{int(time.time())}.eml"
    msg = EmailMessage(policy=default_policy)
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["X-Unsent"] = "1"
    msg.add_alternative(html_content, subtype="html")
    with open(path, "wb") as f:
        f.write(msg.as_bytes())
    try:
        os.startfile(str(path))
    except Exception:
        pass
    return str(path)

def _call_search(plugin, printers, key_for_plugin, value, group_key):
    sig = inspect.signature(plugin.search)
    if len(sig.parameters) >= 4:
        return plugin.search(printers, key_for_plugin, value, group_key)
    return plugin.search(printers, key_for_plugin, value)

def _call_extract(plugin, entry, group_key):
    sig = inspect.signature(plugin.extract)
    if len(sig.parameters) >= 2:
        return plugin.extract(entry, group_key)
    return plugin.extract(entry)

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="OpenTicket runner with plugin architecture")
    p.add_argument("--printers-json", default=str(PRINTERS_JSON_PATH))
    p.add_argument("-p", "--plugin", default="tech")
    args = p.parse_args(argv)

    try:
        printers = _require_json(args.printers_json)
    except Exception as e:
        sys.stderr.write(f"Failed to read printers JSON: {e}\n")
        return 2

    key = args.plugin.strip().lower()
    module_name = PLUGIN_ALIASES.get(key, f"plugins.{key}.plugin")
    try:
        plugin = importlib.import_module(module_name)
    except Exception as e:
        sys.stderr.write(f"Error: could not import plugin '{module_name}': {e}\n")
        return 2

    required = ("prepare", "search", "extract", "make_subject", "make_html")
    if not all(hasattr(plugin, fn) for fn in required):
        sys.stderr.write("Error: plugin must define prepare(), search(), extract(), make_subject(), make_html().\n")
        return 2

    spec = plugin.prepare()

    print("\nSelect group:")
    print("1) Company")
    print("2) Branches")
    group_key = None
    while True:
        g = input("Enter number: ").strip()
        if g == "1":
            group_key = "Company_Grouped"
            break
        if g == "2":
            group_key = "Branches_Grouped"
            break
        print("Invalid choice. Try again.")

    group_list = printers.get(group_key, [])
    if not isinstance(group_list, list) or not group_list:
        sys.stderr.write(f"Error: JSON has no {group_key} entries.\n")
        return 2

    fields = spec.get("search_fields", [])
    if group_key == "Company_Grouped":
        fields = [f for f in fields if f.get("key","").lower() != "id"]
    if not fields:
        sys.stderr.write("Error: no search_fields available.\n")
        return 2

    print("\nSearch by:")
    for i, fdef in enumerate(fields, 1):
        print(f"{i}) {fdef['label']}")

    while True:
        choice = input("Enter number: ").strip()
        if not choice.isdigit() or not (1 <= int(choice) <= len(fields)):
            print("Invalid choice. Try again.")
            continue
        fdef = fields[int(choice) - 1]
        key_for_plugin = fdef["key"]
        label = fdef["label"]
        while True:
            value = input(f"Enter exact {label} (or press Enter to change field): ").strip()
            if not value:
                break
            results = _call_search(plugin, printers, key_for_plugin, value, group_key)
            if not results:
                print("No info found for that value. Try again.")
                continue
            entry = results[0] if len(results) == 1 else _choose(results)
            if not entry:
                print("Canceled. Try again.")
                continue
            data = _call_extract(plugin, entry, group_key)
            if hasattr(plugin, "collect"):
                data = plugin.collect(spec, data)
            to_addr = spec.get("to", "sysmoked@one1.co.il")
            subject = plugin.make_subject(data)
            html_body = plugin.make_html(data, to_addr)
            if _try_outlook_com(to_addr, subject, html_body):
                print("Draft opened in Outlook. You must send manually.")
            else:
                path = _open_eml_draft(to_addr, subject, html_body)
                print("Outlook COM not available; .eml draft opened. You must send manually.")
                print("Draft path:", path)
            return 0
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
