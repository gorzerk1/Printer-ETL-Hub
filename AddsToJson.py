from __future__ import annotations
import argparse
import importlib
import inspect
import json
import sys
from typing import Any, Dict, Tuple, List
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PRINTERS_JSON_PATH = BASE_DIR / "printers.json"
PLUGIN_ALIASES = {"employee": "plugins.Employee", "location": "plugins.Location"}

def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _str2bool(v: str | bool | None) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return True
    s = str(v).strip().lower()
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {v}")

def _import_plugin(name_or_alias: str) -> Tuple[str, Any]:
    key = name_or_alias.strip().lower()
    module_name = PLUGIN_ALIASES.get(key, name_or_alias)
    mod = importlib.import_module(module_name)
    if not hasattr(mod, "prepare") or not hasattr(mod, "run"):
        raise AttributeError(f"plugin '{module_name}' must define prepare() and run(printers, employees_json_path).")
    return module_name, mod

def _execute_plugin(
    mod: Any,
    module_name: str,
    printers: Dict[str, Any],
    printers_path: Path,
    cleanup: bool,
) -> Tuple[Dict[str, Any], bool]:
    try:
        prep_fn = getattr(mod, "prepare")
        if "temp" in inspect.signature(prep_fn).parameters:
            spec: Dict[str, Any] = prep_fn(temp=bool(cleanup))
        else:
            spec = prep_fn()
    except Exception as e:
        sys.stderr.write(f"Error while running prepare() in '{module_name}': {e}\n")
        return printers, False

    employees_json_path = spec.get("employees_json_path")
    data = spec.get("data")
    if not employees_json_path or data is None:
        sys.stderr.write(f"Error: prepare() in '{module_name}' must return 'employees_json_path' and 'data'.\n")
        return printers, False

    employees_json_path = Path(employees_json_path)
    try:
        _save_json(employees_json_path, data)
    except Exception as e:
        sys.stderr.write(f"Error while writing '{employees_json_path}': {e}\n")
        return printers, False

    try:
        updated = mod.run(printers, str(employees_json_path))
    except Exception as e:
        sys.stderr.write(f"Error while running run() in '{module_name}': {e}\n")
        if cleanup:
            try:
                employees_json_path.unlink()
            except Exception:
                pass
        return printers, False

    try:
        _save_json(printers_path, updated)
    except Exception as e:
        sys.stderr.write(f"Error while writing '{printers_path}': {e}\n")
        if cleanup:
            try:
                employees_json_path.unlink()
            except Exception:
                pass
        return printers, False

    if cleanup:
        try:
            employees_json_path.unlink()
        except Exception:
            pass
        print(f"Plugin '{module_name}' applied and temp removed.")
    else:
        print(f"Plugin '{module_name}' applied; temp file kept at '{employees_json_path}'.")
    return updated, True

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Run plugin(s) that prepare employees JSON and update printers.json"
    )
    p.add_argument("--printers-json", default=str(PRINTERS_JSON_PATH), help="Path to printers.json")
    p.add_argument(
        "-p", "--plugin",
        help="Plugin alias or module path (e.g. 'employee' or 'plugins.Employee'). If omitted, run all known plugins."
    )
    p.add_argument(
        "-t", "--temp", type=_str2bool, nargs="?", const=True, default=True,
        help='When true (default), the employees JSON is treated as TEMP and will be removed. '
             'Use "-t false" to keep it for troubleshooting.'
    )
    args = p.parse_args(argv)

    printers_path = Path(args.printers_json)
    try:
        printers = _load_json(printers_path)
    except FileNotFoundError:
        sys.stderr.write(f"Error: printers.json not found at '{printers_path}'.\n")
        return 2
    except json.JSONDecodeError as e:
        sys.stderr.write(f"Error: printers.json at '{printers_path}' is not valid JSON: {e}\n")
        return 2

    cleanup = bool(args.temp)

    if args.plugin:
        try:
            module_name, mod = _import_plugin(args.plugin)
        except Exception as e:
            sys.stderr.write(f"Error: could not import plugin '{args.plugin}': {e}\n")
            return 2
        printers, ok = _execute_plugin(mod, module_name, printers, printers_path, cleanup)
        return 0 if ok else 2

    if not PLUGIN_ALIASES:
        sys.stderr.write("Error: no plugins known and no -p/--plugin specified.\n")
        return 2

    failures: List[str] = []
    for alias, module_name in PLUGIN_ALIASES.items():
        try:
            module_name, mod = _import_plugin(alias)
        except Exception as e:
            sys.stderr.write(f"Error: could not import plugin '{module_name}': {e}\n")
            failures.append(module_name)
            continue
        printers, ok = _execute_plugin(mod, module_name, printers, printers_path, cleanup)
        if not ok:
            failures.append(module_name)

    if failures:
        sys.stderr.write(f"Completed with failures in: {', '.join(failures)}\n")
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
