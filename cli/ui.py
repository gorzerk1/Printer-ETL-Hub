# cli/ui.py
from __future__ import annotations
from typing import Dict, List, Iterable

from settings.config import AppConfig
from core.pipeline import step_labels_from_plan, group_plan_by_step, PlanItem


def cprint(msg: str) -> None:
    # single place to control console output
    print(msg, flush=True)


def print_menu(plan: List[PlanItem], exclude_steps: Iterable[int], exclude_subs: Iterable[tuple[int, int]]) -> None:
    cprint("=== Pipeline Menu (demo) ===")
    labels = step_labels_from_plan(plan)
    grouped = group_plan_by_step(plan)

    for step in sorted(grouped.keys()):
        label = labels.get(step, f"Step {step}")
        cprint(f"Step {step}: {label} ...")
        for it in grouped[step]:
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

    # show current config fields
    cprint(f"[ ] --json = {cfg.printers_json}")
    cprint(f"[ ] --xlsm = {cfg.printers_xlsm}")
    cprint(f"[ ] root = {cfg.root}")
    cprint(f"[ ] logs dir = {cfg.logs_dir}")
    cprint("================================")


def print_config(cfg: AppConfig) -> None:
    for line in cfg.pretty_lines():
        cprint(line)
