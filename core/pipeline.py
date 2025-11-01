# core/pipeline.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Set, Dict
import re

from settings.config import AppConfig

# match your component scripts: don't grab files that start with "_"
_PY_FILE = re.compile(r"^[^_].*\.py$", re.IGNORECASE)


@dataclass
class PlanItem:
    step: int
    substep: Optional[int]
    title: str
    path: Path
    args: List[str]


def _natural_key(name: str):
    parts = re.split(r"(\d+)", name.lower())
    return tuple(int(p) if p.isdigit() else p for p in parts)


def list_scripts(folder: Path) -> List[Path]:
    """Return .py files from a folder in human/numeric order."""
    if not folder.exists():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and _PY_FILE.match(p.name)]
    files.sort(key=lambda p: _natural_key(p.name))
    return files


def parse_excludes(tokens: List[str]) -> Tuple[Set[int], Set[Tuple[int, int]], List[str]]:
    """
    Parse values from --exclude.

    returns:
      - set of whole steps to skip, e.g. {2, 3}
      - set of (step, substep) to skip, e.g. {(2,1), (3,2)}
      - list of invalid tokens (so CLI can print the warning)
    """
    exclude_steps: Set[int] = set()
    exclude_subs: Set[Tuple[int, int]] = set()
    invalid: List[str] = []

    flat: List[str] = []
    for t in tokens:
        flat.extend([s.strip() for s in str(t).split(",") if s.strip()])

    for item in flat:
        if re.fullmatch(r"\d+", item):
            exclude_steps.add(int(item))
        elif re.fullmatch(r"\d+\.\d+", item):
            maj, sub = item.split(".")
            exclude_subs.add((int(maj), int(sub)))
        else:
            invalid.append(item)

    return exclude_steps, exclude_subs, invalid


def build_plan(cfg: AppConfig, *, collect_warnings: bool = False):
    """
    Build the list of steps the pipeline will run.
    Uses the paths from settings.config.AppConfig (so we can point to
    root/convertToJson.py or cli/convert_to_json.py — config decides). :contentReference[oaicite:3]{index=3}
    """
    plan: List[PlanItem] = []
    warnings: List[str] = []
    step_num = 1

    # 1) convert-to-json
    conv_json = cfg.pipeline.convert_to_json
    if conv_json.exists():
        plan.append(
            PlanItem(
                step=step_num,
                substep=None,
                title="Step 1: convertToJson",
                path=conv_json,
                args=[],
            )
        )
    else:
        if collect_warnings:
            warnings.append(f"{conv_json} not found; 'convert to json' will be skipped.")
    step_num += 1

    # 2) component groups (printerError, tonerFinder, tonerType, ...)
    for label, folder in cfg.pipeline.component_groups:
        scripts = list_scripts(folder)
        if not scripts:
            # folder could be empty – not an error
            continue

        major = step_num

        # meta item so menu can show "Step X: label"
        plan.append(
            PlanItem(
                step=major,
                substep=0,
                title=f"Step {major}: {label}",
                path=folder,
                args=[],
            )
        )

        sub = 1
        for script in scripts:
            plan.append(
                PlanItem(
                    step=major,
                    substep=sub,
                    title=f"Step {major}.{sub}: {script.name}",
                    path=script,
                    args=[],
                )
            )
            sub += 1

        step_num += 1

    # 3) convert-to-excel (last)
    conv_excel = cfg.pipeline.convert_to_excel
    if conv_excel.exists():
        plan.append(
            PlanItem(
                step=step_num,
                substep=None,
                title="Step {}: convertToExcel".format(step_num),
                path=conv_excel,
                args=[],
            )
        )
    else:
        if collect_warnings:
            warnings.append(f"{conv_excel} not found; 'convert to excel' will be skipped.")

    if collect_warnings:
        return plan, warnings
    return plan


def step_labels_from_plan(plan: List[PlanItem]) -> Dict[int, str]:
    """
    existing behavior – keep it
    """
    labels: Dict[int, str] = {}
    for it in plan:
        if it.substep == 0:
            # meta: "Step X: Label"
            labels[it.step] = it.title.split(":", 1)[1].strip()
        elif it.substep is None and it.step not in labels:
            labels[it.step] = it.title
    return labels


# 👇 NEW: used by cli.ui so UI doesn’t have to regroup the list
def group_plan_by_step(plan: List[PlanItem]) -> Dict[int, List[PlanItem]]:
    grouped: Dict[int, List[PlanItem]] = {}
    for it in plan:
        grouped.setdefault(it.step, []).append(it)
    return grouped
