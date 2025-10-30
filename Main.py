from __future__ import annotations
import argparse
import logging
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Set, Dict

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs" / "main"
DEFAULT_JSON = "printers.json"
DEFAULT_XLSM = "printers.xlsm"

def _str2bool(v: str) -> bool:
    s = v.strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError("Boolean value expected (true/false).")

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run printer pipeline in folder-aware order.")
    p.add_argument("-m", "--menu", action="store_true")
    p.add_argument("-e", "--exclude", action="append", default=[])
    p.add_argument("-d", "--debug", type=_str2bool, default=False)
    p.add_argument("-l", "--logs", type=_str2bool, default=True)
    p.add_argument("--json", default=DEFAULT_JSON)
    p.add_argument("--xlsm", default=DEFAULT_XLSM)
    return p.parse_args()

def setup_logging(enable_logs: bool) -> Optional[Path]:
    if not enable_logs:
        return None
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = LOG_DIR / f"{ts}.log"
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt=datefmt,
        handlers=[logging.FileHandler(logfile, encoding="utf-8")],
    )
    logging.info("=== Printer Pipeline Start ===")
    logging.info("Working dir: %s", ROOT)
    logging.info("Python exe : %s", sys.executable)
    logging.info("Python ver : %s", sys.version.replace("\n", " "))
    logging.info("Platform   : %s %s (%s)", platform.system(), platform.release(), platform.machine())
    return logfile

def flog(msg: str, level: int = logging.INFO) -> None:
    if logging.getLogger().handlers:
        logging.log(level, msg)

def cprint(msg: str) -> None:
    print(msg, flush=True)

def cdebug(msg: str, debug: bool) -> None:
    if debug:
        print(msg, flush=True)

_PY_FILE = re.compile(r"^[^_].*\.py$", re.IGNORECASE)

def list_scripts(folder: Path) -> List[Path]:
    if not folder.exists():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and _PY_FILE.match(p.name)]
    def _key(p: Path):
        parts = re.split(r"(\d+)", p.name.lower())
        return tuple(int(x) if x.isdigit() else x for x in parts)
    return sorted(files, key=_key)

@dataclass
class PlanItem:
    step: int
    substep: Optional[int]
    title: str
    path: Path
    args: List[str]

@dataclass
class StepResult:
    item: PlanItem
    ok: bool
    exit_code: Optional[int]
    elapsed_s: float
    note: str = ""

def parse_excludes(tokens: List[str]) -> Tuple[Set[int], Set[Tuple[int,int]]]:
    exclude_steps: Set[int] = set()
    exclude_subs: Set[Tuple[int,int]] = set()
    raw: List[str] = []
    for t in tokens:
        raw.extend([s.strip() for s in str(t).split(",") if s.strip()])
    for t in raw:
        if re.fullmatch(r"\d+", t):
            exclude_steps.add(int(t))
        elif re.fullmatch(r"\d+\.\d+", t):
            major, minor = t.split(".")
            exclude_subs.add((int(major), int(minor)))
        else:
            cprint(f"[WARN] Ignoring invalid --exclude value: {t}")
    return exclude_steps, exclude_subs

def run_script(item: PlanItem, debug: bool) -> StepResult:
    cmd = [sys.executable, str(item.path), *item.args]
    cdebug(f"\n----- {item.title} -----", debug)
    cdebug(f"Script: {item.path}", debug)
    cdebug(f"Command: {cmd!r}", debug)
    flog("")
    flog(f"----- {item.title} -----")
    flog(f"Script path: {item.path}")
    flog(f"Command   : {cmd!r}")
    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    except Exception as e:
        elapsed = time.perf_counter() - start
        msg = f"{item.title}: failed to launch: {e!r}"
        flog(msg, level=logging.ERROR)
        cdebug(f"[ERROR] {msg}", debug)
        cprint(f"✗ {item.title} (launch error)")
        return StepResult(item, ok=False, exit_code=None, elapsed_s=elapsed, note="launch error")
    elapsed = time.perf_counter() - start
    if proc.stdout:
        flog(f"{item.title} stdout:\n{proc.stdout.rstrip()}")
        cdebug(f"\n{item.title} stdout:\n{proc.stdout.rstrip()}", debug)
    if proc.stderr:
        flog(f"{item.title} stderr:\n{proc.stderr.rstrip()}", level=logging.WARNING)
        cdebug(f"\n{item.title} stderr:\n{proc.stderr.rstrip()}", debug)
    flog(f"{item.title}: exit code {proc.returncode} ({elapsed:.2f}s)")
    if proc.returncode == 0:
        cprint(f"✓ {item.title} ({elapsed:.2f}s)")
        return StepResult(item, ok=True, exit_code=0, elapsed_s=elapsed)
    else:
        cprint(f"✗ {item.title} failed (exit {proc.returncode}) after {elapsed:.2f}s")
        return StepResult(item, ok=False, exit_code=proc.returncode, elapsed_s=elapsed)

def build_plan(json_name: str, xlsm_name: str) -> List[PlanItem]:
    plan: List[PlanItem] = []
    step_num = 1
    conv = ROOT / "convertToJson.py"
    if conv.exists():
        plan.append(PlanItem(step=step_num, substep=None, title="Step 1: convertToJson", path=conv, args=[]))
    else:
        cprint("✗ Step 1: convertToJson.py not found (will be skipped)")
    step_num += 1
    groups = [
        ("TonerFinder", ROOT / "Component" / "tonerFinder"),
        ("printerError", ROOT / "Component" / "printerError"),
        ("tonerType", ROOT / "Component" / "tonerType"),
    ]
    for label, folder in groups:
        scripts = list_scripts(folder)
        if not scripts:
            continue
        major = step_num
        plan.append(PlanItem(step=major, substep=0, title=f"Step {major}: {label}", path=scripts[0], args=[]))
        for i, p in enumerate(scripts, start=1):
            plan.append(PlanItem(step=major, substep=i, title=f"Step {major}.{i}: {p.stem}", path=p, args=[]))
        step_num += 1
    conv_excel = ROOT / "convertToExcel.py"
    if conv_excel.exists():
        plan.append(PlanItem(step=step_num, substep=None, title=f"Step {step_num}: convertToExcel", path=conv_excel, args=[json_name, xlsm_name]))
    else:
        cprint(f"✗ convertToExcel.py not found at {conv_excel} (will be skipped)")
    return plan

def step_labels_from_plan(plan: List[PlanItem]) -> Dict[int, str]:
    labels: Dict[int, str] = {}
    for it in plan:
        if it.substep == 0:
            labels[it.step] = it.title.split(":", 1)[1].strip()
    for it in plan:
        if it.step not in labels:
            label = it.title.split(":", 1)[1].strip() if ":" in it.title else it.path.stem
            labels[it.step] = label
    return labels

def print_menu(plan: List[PlanItem], exclude_steps: Set[int], exclude_subs: Set[Tuple[int,int]]) -> None:
    cprint("=== Pipeline Menu (demo) ===")
    labels = step_labels_from_plan(plan)
    by_step: Dict[int, List[PlanItem]] = {}
    for it in plan:
        by_step.setdefault(it.step, []).append(it)
    for step in sorted(by_step.keys()):
        cprint(f"Step {step}: {labels[step]} ...")
        for it in by_step[step]:
            if it.substep == 0:
                continue
            excluded = (it.step in exclude_steps) or ((it.substep is not None) and ((it.step, it.substep) in exclude_subs))
            flag = "[X]" if excluded else "[ ]"
            if it.substep is None:
                cprint(f"{flag} Step {it.step}: {it.path.name}")
            else:
                cprint(f"{flag} Step {it.step}.{it.substep}: {it.path.name}")
    cprint("====================================")

def print_param_menu(args: argparse.Namespace, exclude_steps: Set[int], exclude_subs: Set[Tuple[int,int]]) -> None:
    cprint("=== Parameters Menu (demo) ===")
    cprint(f"[{'X' if args.menu else ' '}] --menu")
    cprint(f"[{'X' if args.logs else ' '}] --logs = {args.logs}")
    cprint(f"[{'X' if args.debug else ' '}] --debug = {args.debug}")
    if exclude_steps or exclude_subs:
        all_ex = [str(s) for s in sorted(exclude_steps)]
        all_ex += [f"{m}.{n}" for m, n in sorted(exclude_subs)]
        cprint(f"[X] --exclude = {', '.join(all_ex)}")
    else:
        cprint("[ ] --exclude")
    cprint(f"[ ] --json = {args.json}")
    cprint(f"[ ] --xlsm = {args.xlsm}")
    cprint(f"[ ] root = {ROOT}")
    cprint(f"[ ] logs dir = {LOG_DIR}")
    cprint("================================")

def main() -> None:
    args = parse_args()
    logfile = setup_logging(args.logs)
    try:
        exclude_steps, exclude_subs = parse_excludes(args.exclude)
        plan = build_plan(args.json, args.xlsm)
        labels = step_labels_from_plan(plan)
        if args.menu:
            print_menu(plan, exclude_steps, exclude_subs)
            print_param_menu(args, exclude_steps, exclude_subs)
            flog("Menu displayed; exiting by request.")
            return
        results: List[StepResult] = []
        current_major = None
        for it in plan:
            if current_major != it.step:
                current_major = it.step
                label = labels.get(it.step, it.title.split(":", 1)[1].strip() if ":" in it.title else it.path.stem)
                cprint(f"Step {it.step}: {label} ...")
            if it.substep == 0:
                continue
            if it.substep is None:
                if it.step in exclude_steps:
                    cprint(f"[skip] Step {it.step}")
                    continue
            else:
                if (it.step in exclude_steps) or ((it.step, it.substep) in exclude_subs):
                    cprint(f"[skip] Step {it.step}.{it.substep}")
                    continue
            results.append(run_script(it, args.debug))
        flog("")
        failures = [r for r in results if not r.ok]
        if failures:
            cprint("\nSome steps failed. See log for details.")
            for r in failures:
                title = f"Step {r.item.step}" if r.item.substep is None else f"Step {r.item.step}.{r.item.substep}"
                flog(f"[FAIL] {title} | exit={r.exit_code} | note={r.note}", level=logging.ERROR)
            flog("=== Pipeline End (with failures) ===")
        else:
            cprint("\nAll steps completed successfully.")
            flog("All steps completed successfully.")
            flog("=== Pipeline End ===")
    finally:
        if args.logs and logfile is not None:
            flog(f"Log saved to: {logfile}")
            if args.debug:
                cprint(f"(log: {logfile})")

if __name__ == "__main__":
    main()
