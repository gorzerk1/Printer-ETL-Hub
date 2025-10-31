# settings/logging_setup.py
from __future__ import annotations
import logging
import platform
import sys
from datetime import datetime
from pathlib import Path

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
    logging.info("=== Printer Pipeline Start ===")
    logging.info("Python exe : %s", sys.executable)
    logging.info("Python ver : %s", sys.version.replace("\n", " "))
    logging.info("Platform   : %s %s (%s)", platform.system(), platform.release(), platform.machine())
    return logfile

def flog(msg: str, level: int = logging.INFO) -> None:
    if logging.getLogger().handlers:
        logging.log(level, msg)
