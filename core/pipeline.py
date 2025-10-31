# core/pipeline.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Set, Dict
import re

from settings.config import AppConfig

_PY_FILE = re.compile(r"^[^_].*\.py$", re.IGNORECASE)

@dataclass
class PlanItem:
    step: int
    substep: Optional[int]
    title: str
    path: Path
    args: List[str]

def list_scripts(folder: Path) -> List[Path]:
    if not folder.exists():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and _PY_FILE.match(p.name)]

    def _key(p: Path):
        parts = re.split(r"(\d+)", p.name.lower())
        return tuple(int(x) if x.isdigit() else x for x in parts)

    return sorted(files, key=_key)

def parse_excludes(tokens: List[str]) -> Tuple[Set[int], Set[Tuple[int, int]], List[str]]:
    exclude_steps: Set[int] = set()
    exclude_subs: Set[Tuple[int, int]] = set()
    invalid: List[str] = []
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
            invalid.append(t)
    return exclude_steps, exclude_subs, invalid

def build_plan(cfg: AppConfig) -> List[PlanItem]:
    plan: List[PlanItem] = []
    step_num = 1

    # 1) convertToJson.py
    conv = cfg.pipeline.convert_to_json
    if conv.exists():
        plan.append(
            PlanItem(
                step=step_num,
                substep=None,
                title="Step 1: convertToJson",
                path=conv,
                args=[],
            )
        )
    else:
        # we DON'T print here — CLI can print; core stays silent
        pass
    step_num += 1

    # 2) component groups (from config!)
    for label, folder in cfg.pipeline.component_groups:
        scripts = list_scripts(folder)
        if not scripts:
            continue
        major = step_num
        # meta item
        plan.append(
            PlanItem(
                step=major,
                substep=0,
                title=f"Step {major}: {label}",
                path=scripts[0],
                args=[],
            )
        )
        for i, p in enumerate(scripts, start=1):
            plan.append(
                PlanItem(
                    step=major,
                    substep=i,
                    title=f"Step {major}.{i}: {p.stem}",
                    path=p,
                    args=[],
                )
            )
        step_num += 1

    # 3) convertToExcel.py
    conv_excel = cfg.pipeline.convert_to_excel
    if conv_excel.exists():
        plan.append(
            PlanItem(
                step=step_num,
                substep=None,
                title=f"Step {step_num}: convertToExcel",
                path=conv_excel,
                args=[cfg.default_json, cfg.default_xlsm],
            )
        )
    else:
        # let CLI print about missing script
        pass

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
