# cli/main.py
from __future__ import annotations

from settings.arguments import parse_args
from settings.config import AppConfig
from cli.ui import print_config
from cli.command import run_pipeline


def main() -> None:
    args = parse_args()
    cfg = AppConfig.from_args(args)

    # --show-config stays here, but we delegate to cfg.pretty_lines()
    if getattr(args, "show_config", False):
        print_config(cfg)
        return

    exit_code = run_pipeline(args, cfg)
    if exit_code != 0:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
