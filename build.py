#!/usr/bin/env python3
"""riscv-bench: кросс-сборка ML-фреймворка для RISC-V платы и упаковка в папку-бандл.

    python3 build.py <этап> [--framework openvino] [--model resnet50] [--jobs N] [--force]

Это только точка входа: разбор аргументов и запуск этапов по порядку.
Вся работа - в пакете rvb/ (по файлу на этап в rvb/stages/), настройки - в configs/*.toml.
Подробности: README.md и docs/.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))              # чтобы `import rvb` работал при запуске из любой папки

from rvb.context import Ctx                # noqa: E402
from rvb.stages import BY_NAME, STAGES     # noqa: E402
from rvb.stamps import is_done             # noqa: E402
from rvb.util import note                  # noqa: E402


def parse_args():
    stage_help = "\n".join(f"  {s.NAME:<10} {s.HELP}" for s in STAGES)
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Этапы:\n" + stage_help + "\n  all        все этапы подряд")
    parser.add_argument("stage", choices=[*BY_NAME, "all"], metavar="этап",
                        help="один из этапов (см. ниже) или all")
    parser.add_argument("--framework", default="openvino", help="имя файла в configs/frameworks/ без .toml")
    parser.add_argument("--model", default="resnet50", help="имя файла в configs/models/ без .toml")
    parser.add_argument("--jobs", type=int, default=0, help="число параллельных задач сборки (по умолчанию все ядра)")
    parser.add_argument("--force", action="store_true", help="повторить этап, даже если он уже выполнялся")
    return parser.parse_args()


def main():
    args = parse_args()
    ctx = Ctx(ROOT, args.framework, args.model, jobs=args.jobs, force=args.force)
    stages = STAGES if args.stage == "all" else [BY_NAME[args.stage]]
    for stage in stages:
        # при `all` тяжёлые этапы с меткой «сделано» пропускаем; отдельно названный этап выполняется всегда
        if args.stage == "all" and stage.SKIP_IF_DONE and is_done(ctx, stage.NAME):
            note(f"{stage.NAME}: пропуск (уже сделан, --force чтобы повторить)")
            continue
        stage.run(ctx)


if __name__ == "__main__":
    main()
