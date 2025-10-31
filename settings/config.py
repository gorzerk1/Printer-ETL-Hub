# settings/config.py
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
    printers_json: Path
    printers_xlsm: Path
    draft_xlsm: Path
    data_dir: Path
    pipeline: PipelineConfig

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
            convert_to_json = root / "cli" / "convert_to_json.py",   # or root files if you kept them
            convert_to_excel = root / "cli" / "convert_to_excel.py",
            component_groups = [
                ("TonerFinder", root / "Component" / "tonerFinder"),
                ("printerError", root / "Component" / "printerError"),
                ("tonerType", root / "Component" / "tonerType"),
            ],
        )

        return cls(
            root = root,
            logs_dir = root / "logs" / "main",
            # 🔽 defaults under data/, but overridable via env
            printers_json = env_path("PRINTERS_JSON", root / "printers.json"),
            printers_xlsm = env_path("PRINTERS_XLSM", root / "printers.xlsm"),
            draft_xlsm    = env_path("PRINTERS_DRAFT_XLSM", data_dir / "printersDraft.xlsm"),
            data_dir = data_dir,
            pipeline = pipeline,
        )

    @classmethod
    def from_args(cls, args) -> "AppConfig":
        cfg = cls.load()
        # CLI flags (if provided) beat env/defaults
        if getattr(args, "json", None):
            p = Path(args.json).expanduser()
            cfg.printers_json = p if p.is_absolute() else cfg.root / p
        if getattr(args, "xlsm", None):
            p = Path(args.xlsm).expanduser()
            cfg.printers_xlsm = p if p.is_absolute() else cfg.root / p
        return cfg
