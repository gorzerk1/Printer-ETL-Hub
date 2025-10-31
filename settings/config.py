# settings/config.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class PipelineConfig:
    convert_to_json: Path
    convert_to_excel: Path
    component_groups: list[tuple[str, Path]]

@dataclass
class AppConfig:
    root: Path
    logs_dir: Path
    default_json: str
    default_xlsm: str
    pipeline: PipelineConfig

    @classmethod
    def load(cls) -> "AppConfig":
        # detect project root (same idea as your old ROOT = Path(__file__).resolve().parent)
        root = Path(__file__).resolve().parents[1]

        component_root = root / "Component"

        pipeline_cfg = PipelineConfig(
            convert_to_json = root / "convertToJson.py",
            convert_to_excel = root / "convertToExcel.py",
            component_groups = [
                ("TonerFinder", component_root / "tonerFinder"),
                ("printerError", component_root / "printerError"),
                ("tonerType", component_root / "tonerType"),
            ],
        )

        return cls(
            root = root,
            logs_dir = root / "logs" / "main",
            default_json = "printers.json",
            default_xlsm = "printers.xlsm",
            pipeline = pipeline_cfg,
        )

    @classmethod
    def from_args(cls, args) -> "AppConfig":
        cfg = cls.load()
        # allow CLI overrides (like your original --json/--xlsm)
        if getattr(args, "json", None):
            cfg.default_json = args.json
        if getattr(args, "xlsm", None):
            cfg.default_xlsm = args.xlsm
        return cfg
