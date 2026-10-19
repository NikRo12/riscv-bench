"""Этап verify: проверить готовый бандл на сервере, не запуская его (RISC-V на x86 не запустить).

Что проверяется (список файлов и строк берётся из раздела [verify] конфига фреймворка):
    1. каждый файл из [verify] elf - действительно ELF под RISC-V (readelf -h);
    2. все библиотеки, которые эти файлы требуют (NEEDED), лежат в бандле
       либо относятся к системным библиотекам платы (target.toml, [board] system_libs);
    3. в бинарниках есть строки из [[verify.contains]] - доказательство, что патчи попали в сборку;
    4. в бандле есть run.sh, MANIFEST.txt и model/.
"""
import subprocess

from ..stamps import mark_done
from ..util import die, note, say

NAME = "verify"
HELP = "проверить бандл: архитектура RISC-V, зависимости, строки патчей"
SKIP_IF_DONE = False


def _readelf(ctx, flag, path):
    result = subprocess.run([ctx.toolchain["readelf"], flag, str(path)],
                            env=ctx.env(), capture_output=True, text=True)
    return result.stdout


def _check_architecture(ctx, out_dir, elf_files):
    good = True
    for rel in elf_files:
        path = out_dir / rel
        is_riscv = path.exists() and "RISC-V" in _readelf(ctx, "-h", path)
        note(f"[{'ok' if is_riscv else '!!'}] архитектура RISC-V: {rel}")
        good &= is_riscv
    return good


def _check_dependencies(ctx, out_dir, elf_files):
    """Библиотеки из NEEDED должны быть в бандле, если это не системные библиотеки платы."""
    system_prefixes = tuple(ctx.board["system_libs"])
    in_bundle = {p.name for p in out_dir.rglob("*")}
    good = True
    for rel in elf_files:
        path = out_dir / rel
        if not path.exists():
            continue
        for line in _readelf(ctx, "-d", path).splitlines():
            if "(NEEDED)" not in line:
                continue
            lib = line.split("[")[1].split("]")[0]
            if lib not in in_bundle and not lib.startswith(system_prefixes):
                note(f"[!!] {rel} требует {lib}, его нет в бандле")
                good = False
    return good


def _check_strings(out_dir, rules):
    """Поиск строк в байтах бинарника (так проверяем, что патч попал в сборку)."""
    good = True
    for rule in rules:
        path = out_dir / rule["file"]
        blob = path.read_bytes() if path.exists() else b""
        for text in rule["strings"]:
            found = text.encode() in blob
            note(f"[{'ok' if found else '!!'}] в {rule['file']} есть '{text}'")
            good &= found
    return good


def _check_layout(out_dir):
    good = True
    for rel in ["run.sh", "MANIFEST.txt", "model"]:
        exists = (out_dir / rel).exists()
        note(f"[{'ok' if exists else '!!'}] {rel}")
        good &= exists
    return good


def run(ctx):
    say("verify: проверка бандла (на сервере, без запуска)")
    out_dir = ctx.out
    if not out_dir.is_dir():
        die(f"нет бандла {out_dir}: сначала выполните этап package")
    verify_cfg = ctx.fw["verify"]
    results = [
        _check_architecture(ctx, out_dir, verify_cfg["elf"]),
        _check_dependencies(ctx, out_dir, verify_cfg["elf"]),
        _check_strings(out_dir, verify_cfg.get("contains", [])),
        _check_layout(out_dir),
    ]
    if not all(results):
        die("verify: есть проблемы (см. [!!])")
    note("")
    note("Готово. Перенос на плату: scp out/<имя>.tar.gz student@<плата>:~")
    mark_done(ctx, NAME)
