# cli/command.py
from __future__ import annotations
from typing import List, Tuple
from settings.config import AppConfig
from settings.logging_setup import setup_logging, flog
from core.pipeline import (
    build_plan,
    parse_excludes,
    step_labels_from_plan,
    PlanItem,
)
from adapters.script_runner import run_script
from cli.ui import cprint, print_menu, print_param_menu


def run_pipeline(args, cfg: AppConfig) -> int:
    """
    Run the actual ETL pipeline: build plan, apply excludes, run steps, summarize.
    Returns process-like exit code (0=ok, >0 = had failures).
    """
    logfile = setup_logging(cfg.logs_dir, enable_logs=args.logs)

    # Excludes
    exclude_steps, exclude_subs, invalid_tokens = parse_excludes(args.exclude)
    for bad in invalid_tokens:
        cprint(f"[WARN] Ignoring invalid --exclude value: {bad}")
        flog(f"[WARN] Ignoring invalid --exclude value: {bad}")

    # Build plan
    plan = build_plan(cfg)

    # Friendly notices if configured step scripts are missing
    if not cfg.pipeline.convert_to_json.exists():
        cprint("✗ Step 1: convert_to_json.py not found (will be skipped)")
        flog("convert_to_json.py not found (will be skipped)")
    if not cfg.pipeline.convert_to_excel.exists():
        cprint(f"✗ convert_to_excel.py not found at {cfg.pipeline.convert_to_excel} (will be skipped)")
        flog(f"convert_to_excel.py not found at {cfg.pipeline.convert_to_excel} (will be skipped)")

    # If user asked for menu – only show, then exit
    if args.menu:
        print_menu(plan, exclude_steps, exclude_subs)
        print_param_menu(args, cfg, exclude_steps, exclude_subs)
        flog("Menu displayed; exiting by request.")
        return 0

    labels = step_labels_from_plan(plan)
    current_major = None
    results = []

    try:
        for it in plan:
            # announce each major step once
            if current_major != it.step:
                current_major = it.step
                label = labels.get(
                    it.step,
                    it.title.split(":", 1)[1].strip() if ":" in it.title else it.path.stem,
                )
                cprint(f"Step {it.step}: {label} ...")

            # meta items are headings only
            if it.substep == 0:
                continue

            # apply excludes
            if it.substep is None:
                if it.step in exclude_steps:
                    cprint(f"[skip] Step {it.step}")
                    continue
            else:
                if (it.step in exclude_steps) or ((it.step, it.substep) in exclude_subs):
                    cprint(f"[skip] Step {it.step}.{it.substep}")
                    continue

            # run the step
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
                title = f"Step {r.item.step}" if r.item.substep is None else f"Step {r.item.step}.{r.item.substep}"
                flog(f"[FAIL] {title} | exit={r.exit_code} | note={r.note}", level=40)
            flog("=== Pipeline End (with failures) ===")
            return 1
        else:
            cprint("\nAll steps completed successfully.")
            flog("All steps completed successfully.")
            flog("=== Pipeline End ===")
            return 0

    finally:
        if args.logs and logfile is not None:
            flog(f"Log saved to: {logfile}")
            if args.debug:
                cprint(f"(log: {logfile})")
