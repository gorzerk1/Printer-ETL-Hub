# core/openticket/plugins.py
from __future__ import annotations
from typing import Dict
import importlib
from importlib import resources

ALIASES: Dict[str, str] = {
    "tech": "plugins.openticket.PrinterTechnician",
    "toner": "plugins.openticket.TonerOrder",
    "drum": "plugins.openticket.DrumOrder",
}

def _discover_package_plugins() -> Dict[str, str]:
    found: Dict[str, str] = {}
    try:
        base = resources.files("plugins")
        for entry in base.iterdir():
            if entry.is_dir():
                plugin_py = entry / "plugin.py"
                if plugin_py.exists():
                    key = entry.name.lower()
                    found[key] = f"plugins.{entry.name}.plugin"
    except Exception:
        pass
    return found

def available_plugins() -> Dict[str, str]:
    discovered = _discover_package_plugins()
    merged = dict(discovered)
    merged.update(ALIASES)
    return merged

def load_plugin(key: str):
    key_l = key.lower()
    mod = available_plugins().get(key_l, f"plugins.{key_l}.plugin")
    return importlib.import_module(mod)
