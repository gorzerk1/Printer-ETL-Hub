# cli/command.py
from __future__ import annotations

from settings.config import AppConfig
from settings.logging_setup import cli_logging, flog
from core.pipeline import (
    build_plan,
    parse_excludes,
    step_labels_from_plan,
)
from adapters.script_runner import run_script, summarize_results
from cli.ui import cprint, print_menu, print_param_menu


def run_pipeline(args, cfg: AppConfig) -> int:
    """
    Run the actual ETL pipeline: build plan, apply excludes, run steps, summarize.
    Returns process-like exit code (0=ok, >0 = had failures).
    """
    with cli_logging(cfg.logs_dir, enable_logs=args.logs) as logfile:
        # Excludes
        exclude_steps, exclude_subs, invalid_tokens = parse_excludes(args.exclude)
        for bad in invalid_tokens:
            cprint(f"[WARN] Ignoring invalid --exclude value: {bad}")
            flog(f"[WARN] Ignoring invalid --exclude value: {bad}")

        # Build plan (and collect missing-script warnings)
        plan, warns = build_plan(cfg, collect_warnings=True)
        for w in warns:
            cprint(f"[WARN] {w}")
            flog(w)

        # If user asked for menu – only show, then exit
        if args.menu:
            print_menu(plan, exclude_steps, exclude_subs)
            print_param_menu(args, cfg, exclude_steps, exclude_subs)
            flog("Menu displayed; exiting by request.")
            return 0

        labels = step_labels_from_plan(plan)
        current_major = None
        results = []

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

        ok, failed = summarize_results(results)

        if not ok:
            cprint("\nSome steps failed. See log for details.")
            for r in failed:
                title = f"Step {r.item.step}" if r.item.substep is None else f"Step {r.item.step}.{r.item.substep}"
                flog(f"[FAIL] {title} | exit={r.exit_code} | note={r.note}", level=40)
            flog("=== Pipeline End (with failures) ===")
            return 1

        cprint("\nAll steps completed successfully.")
        flog("All steps completed successfully.")
        flog("=== Pipeline End ===")

        # logfile is logged in cli_logging() finally
        if args.debug and logfile is not None:
            cprint(f"(log: {logfile})")

        return 0
