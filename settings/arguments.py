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


# =========================
# CLI / pipeline arguments
# =========================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run printer pipeline in folder-aware order.")
    p.add_argument("-m", "--menu", action="store_true")
    p.add_argument("-e", "--exclude", action="append", default=[])
    p.add_argument("-d", "--debug", type=_str2bool, default=False)
    p.add_argument("-l", "--logs", type=_str2bool, default=True)
    p.add_argument(
        "--show-config",
        action="store_true",
        help="print resolved config paths and exit",
    )
    return p


def parse_args() -> argparse.Namespace:
    parser = build_parser()
    return parser.parse_args()


# =========================
# Plugin / per-script arguments
# (printerError, tonerFinder, tonerType)
# =========================
def build_plugin_parser(description: str = "Printer plugin") -> argparse.ArgumentParser:
    """
    Shared arg parser for plugins under plugins/printerError, plugins/tonerFinder,
    plugins/tonerType, so each script doesn't need to re-declare the same flags.
    """
    p = argparse.ArgumentParser(description=description)
    # let plugin override printers.json
    p.add_argument(
        "-j",
        "--json",
        dest="json_path",
        help="Path to printers.json (defaults to config / project root)",
    )
    # run only on one printer
    p.add_argument(
        "-ip",
        "--only-ip",
        dest="only_ip",
        help="Process only this printer IP",
    )
    # network bits
    p.add_argument(
        "-t",
        "--timeout",
        dest="timeout",
        type=float,
        help="Network timeout in seconds (overrides config)",
    )
    p.add_argument(
        "-c",
        "--community",
        dest="community",
        help="SNMP community (overrides config)",
    )
    # logging for individual scripts
    p.add_argument(
        "--log",
        dest="log",
        action="store_true",
        default=False,
        help="Enable file logging for this plugin run",
    )
    # verbose
    p.add_argument(
        "-d",
        "--debug",
        dest="debug",
        action="store_true",
        default=False,
        help="Print debug info to stdout",
    )
    return p
