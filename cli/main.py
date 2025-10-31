# cli/main.py
from __future__ import annotations
from pathlib import Path

from settings.arguments import parse_args
from settings.config import AppConfig
from settings.logging_setup import setup_logging, flog
from core.pipeline import (
    build_plan,
    parse_excludes,
    step_labels_from_plan,
    PlanItem,
)
from adapters.script_runner import run_script, StepResult

def cprint(msg: str) -> None:
    print(msg, flush=True)

def cdebug(msg: str, debug: bool) -> None:
    if debug:
        print(msg, flush=True)

def print_menu(plan: list[PlanItem], exclude_steps, exclude_subs) -> None:
    cprint("=== Pipeline Menu (demo) ===")
    labels = step_labels_from_plan(plan)
    by_step: dict[int, list[PlanItem]] = {}
    for it in plan:
        by_step.setdefault(it.step, []).append(it)
    for step in sorted(by_step.keys()):
        cprint(f"Step {step}: {labels[step]} ...")
        for it in by_step[step]:
            if it.substep == 0:
                continue
            excluded = (it.step in exclude_steps) or (
                (it.substep is not None) and ((it.step, it.substep) in exclude_subs)
            )
            flag = "[X]" if excluded else "[ ]"
            if it.substep is None:
                cprint(f"{flag} Step {it.step}: {it.path.name}")
            else:
                cprint(f"{flag} Step {it.step}.{it.substep}: {it.path.name}")
    cprint("====================================")

def print_param_menu(args, cfg: AppConfig, exclude_steps, exclude_subs) -> None:
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

    cprint(f"[ ] --json = {cfg.default_json}")
    cprint(f"[ ] --xlsm = {cfg.default_xlsm}")
    cprint(f"[ ] root = {cfg.root}")
    cprint(f"[ ] logs dir = {cfg.logs_dir}")
    cprint("================================")

def main() -> None:
    args = parse_args()
    cfg = AppConfig.from_args(args)

    logfile = setup_logging(cfg.logs_dir, enable_logs=args.logs)

    # parse excludes
    exclude_steps, exclude_subs, invalid_tokens = parse_excludes(args.exclude)
    for bad in invalid_tokens:
        cprint(f"[WARN] Ignoring invalid --exclude value: {bad}")
        flog(f"[WARN] Ignoring invalid --exclude value: {bad}")

    # build plan (now uses config)
    plan = build_plan(cfg)

    # but we still want to tell user if certain scripts are missing (like old code)
    if not cfg.pipeline.convert_to_json.exists():
        cprint("✗ Step 1: convertToJson.py not found (will be skipped)")
        flog("convertToJson.py not found (will be skipped)")

    if not cfg.pipeline.convert_to_excel.exists():
        cprint(f"✗ convertToExcel.py not found at {cfg.pipeline.convert_to_excel} (will be skipped)")
        flog(f"convertToExcel.py not found at {cfg.pipeline.convert_to_excel} (will be skipped)")

    if args.menu:
        print_menu(plan, exclude_steps, exclude_subs)
        print_param_menu(args, cfg, exclude_steps, exclude_subs)
        flog("Menu displayed; exiting by request.")
        return

    labels = step_labels_from_plan(plan)
    current_major = None
    results: list[StepResult] = []

    try:
        for it in plan:
            # print "Step X: ..." when we enter a new major step
            if current_major != it.step:
                current_major = it.step
                label = labels.get(it.step, it.title.split(":", 1)[1].strip() if ":" in it.title else it.path.stem)
                cprint(f"Step {it.step}: {label} ...")

            # skip meta
            if it.substep == 0:
                continue

            # apply excludes (same logic as your original)
            if it.substep is None:
                if it.step in exclude_steps:
                    cprint(f"[skip] Step {it.step}")
                    continue
            else:
                if (it.step in exclude_steps) or ((it.step, it.substep) in exclude_subs):
                    cprint(f"[skip] Step {it.step}.{it.substep}")
                    continue

            # run script (IO)
            res = run_script(it, cwd=cfg.root, debug=args.debug)
            if res.ok:
                cprint(f"✓ {it.title} ({res.elapsed_s:.2f}s)")
            else:
                cprint(f"✗ {it.title} failed (exit {res.exit_code}) after {res.elapsed_s:.2f}s")
            results.append(res)

        # summarize
        failures = [r for r in results if not r.ok]
        if failures:
            cprint("\nSome steps failed. See log for details.")
            for r in failures:
                title = (
                    f"Step {r.item.step}"
                    if r.item.substep is None
                    else f"Step {r.item.step}.{r.item.substep}"
                )
                flog(f"[FAIL] {title} | exit={r.exit_code} | note={r.note}", level=40)
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
