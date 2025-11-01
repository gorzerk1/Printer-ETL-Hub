from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class PipelineConfig:
    convert_to_json: Path
    convert_to_excel: Path
    component_groups: list[tuple[str, Path]]


@dataclass
class AppConfig:
    root: Path
    logs_dir: Path
    plugin_logs_dir: Path
    printers_json: Path
    printers_xlsm: Path
    draft_xlsm: Path
    data_dir: Path
    pipeline: PipelineConfig
    snmp_default_community: str
    http_default_timeout: float

    @classmethod
    def load(cls) -> "AppConfig":
        root = Path(__file__).resolve().parents[1]
        data_dir = root / "data"

        def env_path(var: str, default: Path) -> Path:
            v = os.getenv(var)
            if not v:
                return default
            p = Path(v).expanduser()
            return p if p.is_absolute() else (root / p)

        pipeline = PipelineConfig(
            convert_to_json=root / "cli" / "convert_to_json.py",
            convert_to_excel=root / "cli" / "convert_to_excel.py",
            component_groups=[
                ("addstojson", root / "plugins" / "addstojson"),
                ("printerError", root / "plugins" / "printerError"),
                ("TonerFinder", root / "plugins" / "tonerFinder"),
                ("TonerType", root / "plugins" / "tonerType"),
            ],
        )

        return cls(
            root=root,
            logs_dir=root / "logs" / "main",
            plugin_logs_dir=root / "logs" / "plugins",
            printers_json=env_path("PRINTERS_JSON", root / "printers.json"),
            printers_xlsm=env_path("PRINTERS_XLSM", root / "printers.xlsm"),
            draft_xlsm=env_path("PRINTERS_DRAFT_XLSM", data_dir / "printersDraft.xlsm"),
            data_dir=data_dir,
            pipeline=pipeline,
            snmp_default_community=os.getenv("PRINTER_SNMP_COMMUNITY", "public"),
            http_default_timeout=float(os.getenv("PRINTER_HTTP_TIMEOUT", "4")),
        )

    @classmethod
    def from_args(cls, args) -> "AppConfig":
        cfg = cls.load()
        if getattr(args, "json", None):
            p = Path(args.json).expanduser()
            cfg.printers_json = p if p.is_absolute() else cfg.root / p
        if getattr(args, "xlsm", None):
            p = Path(args.xlsm).expanduser()
            cfg.printers_xlsm = p if p.is_absolute() else cfg.root / p
        return cfg

    def pretty_lines(self) -> list[str]:
        lines: list[str] = [
            "Resolved configuration:",
            f"root           : {self.root}",
            f"logs_dir       : {self.logs_dir}",
            f"plugin_logs_dir: {self.plugin_logs_dir}",
            f"printers_json  : {self.printers_json}",
            f"printers_xlsm  : {self.printers_xlsm}",
            f"draft_xlsm     : {self.draft_xlsm}",
            f"data_dir       : {self.data_dir}",
            f"SNMP community : {self.snmp_default_community}",
            f"HTTP timeout   : {self.http_default_timeout}",
            f"step: convert_to_json  : {self.pipeline.convert_to_json}",
            f"step: convert_to_excel : {self.pipeline.convert_to_excel}",
        ]
        for name, folder in self.pipeline.component_groups:
            lines.append(f"component {name:12} : {folder}")
        return lines
