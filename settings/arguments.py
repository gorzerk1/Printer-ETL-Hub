# settings/arguments.py
from __future__ import annotations
import argparse

def _str2bool(v: str) -> bool:
    s = v.strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError("Boolean value expected (true/false).")

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run printer pipeline in folder-aware order.")
    p.add_argument("-m", "--menu", action="store_true")
    p.add_argument("-e", "--exclude", action="append", default=[])
    p.add_argument("-d", "--debug", type=_str2bool, default=False)
    p.add_argument("-l", "--logs", type=_str2bool, default=True)
    p.add_argument("--show-config", action="store_true",
                   help="print resolved config paths and exit")
    return p

def parse_args() -> argparse.Namespace:
    parser = build_parser()
    return parser.parse_args()
