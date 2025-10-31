# cli/ui.py
from __future__ import annotations
from typing import Dict, List, Iterable
from settings.config import AppConfig
from core.pipeline import step_labels_from_plan, PlanItem


def cprint(msg: str) -> None:
    # single place to control console output
    print(msg, flush=True)


def print_menu(plan: List[PlanItem], exclude_steps: Iterable[int], exclude_subs: Iterable[tuple[int, int]]) -> None:
    cprint("=== Pipeline Menu (demo) ===")
    labels = step_labels_from_plan(plan)
    by_step: Dict[int, List[PlanItem]] = {}
    for it in plan:
        by_step.setdefault(it.step, []).append(it)

    for step in sorted(by_step.keys()):
        cprint(f"Step {step}: {labels[step]} ...")
        for it in by_step[step]:
            if it.substep == 0:
                # meta/header items – don’t print as a runnable step
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

    # fixed to show current config fields
    cprint(f"[ ] --json = {cfg.printers_json}")
    cprint(f"[ ] --xlsm = {cfg.printers_xlsm}")
    cprint(f"[ ] root = {cfg.root}")
    cprint(f"[ ] logs dir = {cfg.logs_dir}")
    cprint("================================")


def print_config(cfg: AppConfig) -> None:
    cprint("Resolved configuration:")
    cprint(f"root           : {cfg.root}")
    cprint(f"logs_dir       : {cfg.logs_dir}")
    cprint(f"printers_json  : {cfg.printers_json}")
    cprint(f"printers_xlsm  : {cfg.printers_xlsm}")
    cprint(f"draft_xlsm     : {cfg.draft_xlsm}")
    cprint(f"step: convert_to_json  : {cfg.pipeline.convert_to_json}")
    cprint(f"step: convert_to_excel : {cfg.pipeline.convert_to_excel}")
    for name, folder in cfg.pipeline.component_groups:
        cprint(f"component {name:12} : {folder}")
