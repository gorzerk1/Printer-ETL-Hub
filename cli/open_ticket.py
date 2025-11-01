# cli/open_ticket.py
from __future__ import annotations
import argparse, inspect, sys
from typing import Any, Dict, List
from pathlib import Path
from settings.config import AppConfig
from adapters.printers_store import find_printers_json, load_printers
from adapters.mailer import send_via_outlook, write_eml_draft
from core.openticket.plugins import load_plugin, available_plugins

def _choose(items: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    print("\nMultiple matches found:")
    for i, e in enumerate(items, 1):
        print(
            f"{i}. ID={e.get('ID','')}  Name={e.get('Name','')}  "
            f"Serial={e.get('Serial','')}  Printer IP={e.get('Printer IP','')}  "
            f"Type={e.get('Type','')}"
        )
    while True:
        s = input("Pick a number or leave empty to cancel: ").strip()
        if not s:
            return None
        if s.isdigit():
            i = int(s)
            if 1 <= i <= len(items):
                return items[i-1]

def main(argv=None) -> int:
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--printers-json", help="Path to printers.json (defaults to AppConfig)")
    p.add_argument("-p", "--plugin", help="Which plugin to use")
    args = p.parse_args(argv)

    if not args.plugin:
        opts = ", ".join(sorted(available_plugins().keys()))
        sys.stderr.write(
            "You must choose a plugin with --plugin.\n"
            f"Available options: {opts}\n"
            "Example: python -m cli.open_ticket --plugin toner\n"
        )
        return 2

    cfg = AppConfig.load()
    try:
        printers_path: Path = find_printers_json(args.printers_json, project_root=cfg.root)
        printers = load_printers(printers_path)
    except Exception as e:
        sys.stderr.write(f"Failed to read printers JSON: {e}\n")
        return 2

    try:
        plugin = load_plugin(args.plugin)
    except Exception as e:
        sys.stderr.write(f"Error: could not import plugin '{args.plugin}': {e}\n")
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

    group_list = printers.get(group_key, []) or []
    if not group_list:
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

            sig = inspect.signature(plugin.search)
            if len(sig.parameters) >= 4:
                results = plugin.search(printers, key_for_plugin, value, group_key)
            else:
                results = plugin.search(printers, key_for_plugin, value)

            if not results:
                print("No info found for that value. Try again.")
                continue

            if len(results) > 1:
                entry = _choose(results)
                if not entry:
                    print("Canceled.")
                    return 0
            else:
                entry = results[0]

            sig = inspect.signature(plugin.extract)
            if len(sig.parameters) >= 2:
                data = plugin.extract(entry, group_key)
            else:
                data = plugin.extract(entry)

            if hasattr(plugin, "collect"):
                data = plugin.collect(spec, data)

            to_addr = spec.get("to", "sysmoked@one1.co.il")
            subject = plugin.make_subject(data)
            html_body = plugin.make_html(data, to_addr)

            if send_via_outlook(to_addr, subject, html_body):
                print("Draft opened in Outlook. You must send manually.")
            else:
                path = write_eml_draft(to_addr, subject, html_body)
                print("Outlook COM not available; .eml draft opened. You must send manually.")
                print("Draft path:", path)
            return 0

if __name__ == "__main__":
    raise SystemExit(main())
