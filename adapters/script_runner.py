# adapters/script_runner.py
from __future__ import annotations
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from settings.logging_setup import flog
from core.pipeline import PlanItem

class StepResult:
    def __init__(self, item: PlanItem, ok: bool, exit_code: Optional[int], elapsed_s: float, note: str = ""):
        self.item = item
        self.ok = ok
        self.exit_code = exit_code
        self.elapsed_s = elapsed_s
        self.note = note

def run_script(item: PlanItem, cwd: Path, debug: bool) -> StepResult:
    cmd = [sys.executable, str(item.path), *item.args]

    # debug prints (CLI-like, but we keep them here because it's 100% tied to script running)
    if debug:
        print(f"\n----- {item.title} -----", flush=True)
        print(f"Script: {item.path}", flush=True)
        print(f"Command: {cmd!r}", flush=True)

    flog("")
    flog(f"----- {item.title} -----")
    flog(f"Script path: {item.path}")
    flog(f"Command   : {cmd!r}")

    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception as e:
        elapsed = time.perf_counter() - start
        msg = f"{item.title}: failed to launch: {e!r}"
        flog(msg, level=40)
        if debug:
            print(f"[ERROR] {msg}", flush=True)
            print(f"✗ {item.title} (launch error)", flush=True)
        return StepResult(item, ok=False, exit_code=None, elapsed_s=elapsed, note="launch error")

    elapsed = time.perf_counter() - start

    if proc.stdout:
        flog(f"{item.title} stdout:\n{proc.stdout.rstrip()}")
        if debug:
            print(proc.stdout.rstrip(), flush=True)

    if proc.stderr:
        flog(f"{item.title} stderr:\n{proc.stderr.rstrip()}", level=30)
        if debug:
            print(proc.stderr.rstrip(), flush=True)

    flog(f"{item.title}: exit code {proc.returncode} ({elapsed:.2f}s)")

    if proc.returncode == 0:
        # we do NOT print here; CLI prints
        return StepResult(item, ok=True, exit_code=0, elapsed_s=elapsed)
    else:
        return StepResult(item, ok=False, exit_code=proc.returncode, elapsed_s=elapsed)
