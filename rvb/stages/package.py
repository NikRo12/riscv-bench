"""Этап package: собрать папку-бандл, которую куратор переносит на плату.

Содержимое out/<фреймворк>-<модель>/:
    <dest>/      файлы из [[bundle]] (например bin/ и tbb/), симлинки сохраняются
    model/       файлы модели из конфига модели
    run.sh       скрипт замера, сгенерированный из templates/run.sh и [run] конфига
    MANIFEST.txt паспорт: коммиты, патчи, хеши файлов
Рядом лежит архив out/<фреймворк>-<модель>.tar.gz с тем же содержимым.
"""
import fnmatch
import os
import re
import shutil
import tarfile
from pathlib import Path

from ..manifest import write_manifest
from ..stamps import mark_done
from ..util import die, note, say

NAME = "package"
HELP = "собрать папку-бандл (файлы, модель, run.sh, MANIFEST.txt) и архив"
SKIP_IF_DONE = False          # дешёвый; бандл пересобирается каждый раз, старые файлы не остаются


def _copy_bundle_files(ctx, out_dir):
    for block in ctx.fw["bundle"]:
        src_dir = Path(ctx.sub(block["src"]))
        dest_dir = out_dir / block["dest"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        if not src_dir.is_dir():
            die(f"нет каталога {src_dir}: сборка (этап build) ещё не выполнена?")
        for pattern in block["patterns"]:
            hits = [f for f in src_dir.iterdir() if fnmatch.fnmatch(f.name, pattern)]
            if not hits:
                # пустая маска - ошибка, а не тихий пропуск: иначе на плату уедет бандл без нужного файла
                die(f"в {src_dir} нет файлов по маске '{pattern}'")
            for src in hits:
                target = dest_dir / src.name
                if src.is_symlink():
                    os.symlink(os.readlink(src), target)     # ссылка остаётся ссылкой
                else:
                    shutil.copy2(src, target)


def _copy_model(ctx, out_dir):
    model_dir = ctx.root / ctx.model["dir"]
    (out_dir / "model").mkdir()
    for name in ctx.model["files"]:
        src = model_dir / name
        if not src.exists():
            die(f"нет файла модели {src}. Положите файлы модели в {model_dir}/ "
                f"(откуда их взять - в configs/models/{ctx.model_name}.toml и docs/CONFIG.md)")
        shutil.copy2(src, out_dir / "model" / name)


def _bash_quote(text):
    """Строка в одинарных кавычках для bash (внутренняя ' превращается в '\\'')."""
    return "'" + text.replace("'", "'\\''") + "'"


def _render_run_command(command, scenario):
    """Подставить в команду переменные run.sh. Результат - слова для bash-массива CMD."""
    variables = {"bench": '"$BENCH"', "model": '"$MODEL"', "threads": '"$threads"', "batch": '"$batch"',
                 "niter": '"$NITER"', "duration": '"$DURATION"', "report_dir": '"$REPORT_DIR"'}
    for key, value in variables.items():
        command = command.replace("{" + key + "}", value)
    unknown = re.findall(r"\{[A-Za-z_]+\}", command)
    if unknown:
        die(f"в [[run.scenarios]] '{scenario}' неизвестная подстановка {unknown[0]} "
            f"(доступны: {', '.join('{' + k + '}' for k in variables)})")
    return command


def _write_run_script(ctx, out_dir):
    run_cfg = ctx.fw["run"]
    metrics = run_cfg["metrics"]
    scenarios = run_cfg["scenarios"]
    core_sets = ctx.board["core_sets"]
    replacements = {
        "@@BENCH@@": run_cfg["bench"],
        "@@MODEL@@": f"model/{ctx.model['entry']}",
        "@@LIBRARY_DIRS@@": ":".join(f"$HERE/{d}" for d in run_cfg["library_dirs"]),
        "@@CORE_SETS@@": " ".join(f"[{name}]={_bash_quote(cores)}" for name, cores in core_sets.items()),
        "@@DEFAULT_CORES@@": next(iter(core_sets)),
        "@@SCENARIO_NAMES@@": " ".join(sc["name"] for sc in scenarios),
        "@@SC_PARAM@@": " ".join(f"[{sc['name']}]={sc['param']}" for sc in scenarios),
        "@@SC_VALUES@@": " ".join(f"[{sc['name']}]={_bash_quote(' '.join(str(v) for v in sc['values']))}"
                                  for sc in scenarios),
        "@@SC_CPUS@@": " ".join(f"[{sc['name']}]={sc['cpus']}" for sc in scenarios),
        "@@SCENARIO_COMMANDS@@": "\n".join(
            f"cmd_{sc['name']}() {{ CMD=({_render_run_command(sc['command'], sc['name'])}); }}"
            for sc in scenarios),
        "@@METRIC_NAMES@@": " ".join(m["name"] for m in metrics),
        "@@METRIC_PATTERNS@@": " ".join(_bash_quote(m["pattern"]) for m in metrics),
    }
    text = (ctx.root / "templates/run.sh").read_text()
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    script = out_dir / "run.sh"
    script.write_text(text)
    script.chmod(0o755)


def run(ctx):
    say("package: сборка папки для платы")
    out_dir = ctx.out
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    _copy_bundle_files(ctx, out_dir)
    _copy_model(ctx, out_dir)
    _write_run_script(ctx, out_dir)
    write_manifest(ctx, out_dir)

    archive = out_dir.with_suffix(".tar.gz")        # tarfile сам сохраняет симлинки
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(out_dir, arcname=out_dir.name)
    note(f"папка: {out_dir}")
    note(f"архив: {archive} ({archive.stat().st_size / 2**20:.0f} МБ)")
    mark_done(ctx, NAME)
