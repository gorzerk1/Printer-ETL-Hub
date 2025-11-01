# settings/logging_setup.py
from __future__ import annotations
import logging
import platform
import sys
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager


def setup_logging(log_dir: Path, enable_logs: bool) -> Path | None:
    if not enable_logs:
        return None
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = log_dir / f"{ts}.log"
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt=datefmt,
        handlers=[logging.FileHandler(logfile, encoding="utf-8")],
    )
    logging.info("=== Printer ETL start ===")
    logging.info("Python exe : %s", sys.executable)
    logging.info("Python ver : %s", sys.version.replace("\n", " "))
    logging.info("Platform   : %s %s (%s)", platform.system(), platform.release(), platform.machine())
    return logfile


def flog(msg: str, level: int = logging.INFO) -> None:
    if logging.getLogger().handlers:
        logging.log(level, msg)


@contextmanager
def cli_logging(log_dir: Path, enable_logs: bool):
    logfile = setup_logging(log_dir, enable_logs=enable_logs)
    try:
        yield logfile
    finally:
        if enable_logs and logfile is not None:
            flog(f"Log saved to: {logfile}")


# 👇 updated to always add and remove a dedicated file handler for the plugin
@contextmanager
def plugin_logging(log_dir: Path, plugin_name: str, enable_logs: bool = True):
    if not enable_logs:
        # still yield a placeholder so caller logic stays the same
        yield None
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = log_dir / f"{ts}.log"

    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    handler = logging.FileHandler(logfile, encoding="utf-8")
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    root = logging.getLogger()
    if root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        flog(f"=== Plugin: {plugin_name} ===")
        yield logfile
    finally:
        flog(f"[{plugin_name}] log saved to: {logfile}")
        root.removeHandler(handler)
        handler.close()
