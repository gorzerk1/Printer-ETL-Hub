# plugins/base.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple, ContextManager

from settings.config import AppConfig
from settings.logging_setup import plugin_logging
from adapters.printers_store import find_printers_json, load_printers, save_printers


@dataclass
class PluginContext:
    cfg: AppConfig
    json_path: Path
    data: Dict[str, Any]


def load_context_from_args(args, plugin_name: str) -> tuple[PluginContext, ContextManager[None]]:
    """
    Turn parsed args (built by settings.arguments.build_plugin_parser)
    into a context + a logging context manager.
    """
    cfg = AppConfig.load()
    json_path = find_printers_json(args.json_path, project_root=cfg.root)
    data = load_printers(json_path)

    enable_logs = getattr(args, "logs", False) or getattr(args, "log", False)

    # route active_alerts logs to: <data>/printerError/<plugin_name>/files
    if plugin_name in {"snmp_active_alerts", "ledm_active_alerts", "ews_active_alerts"}:
        log_dir = cfg.data_dir / "printerError" / plugin_name / "files"
    else:
        log_dir = cfg.plugin_logs_dir

    log_cm = plugin_logging(log_dir, plugin_name, enable_logs=enable_logs)

    ctx = PluginContext(cfg=cfg, json_path=json_path, data=data)
    return ctx, log_cm


def save_context(ctx: PluginContext) -> None:
    save_printers(ctx.json_path, ctx.data)
