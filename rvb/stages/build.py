"""Этап build: собрать зависимости и фреймворк под RISC-V.

Блоки [[build]] из конфига фреймворка выполняются по порядку (сначала зависимости).
Система сборки выбирается ключом `system` (по умолчанию "cmake"). Чтобы поддержать другую
систему (Bazel, make), напишите функцию с такой же сигнатурой и добавьте её в BUILD_SYSTEMS.
"""
from pathlib import Path

from ..runner import run as run_cmd
from ..stamps import mark_done
from ..util import die, note, say

NAME = "build"
HELP = "собрать oneTBB и фреймворк кросс-компилятором (долго, запускайте в фоне)"
SKIP_IF_DONE = True


def build_cmake(ctx, block):
    """Конфигурация -> сборка -> (если задан install_prefix) установка."""
    name = block["name"]
    source = ctx.sub(block["source"])
    build_dir = Path(ctx.sub(block["build_dir"]))

    configure = ["cmake", "-S", source, "-B", build_dir, "-G", "Ninja",
                 f"-DCMAKE_TOOLCHAIN_FILE={ctx.toolchain_file}",
                 f"-DCMAKE_BUILD_TYPE={block.get('build_type', 'Release')}"]
    if block.get("install_prefix"):
        configure.append(f"-DCMAKE_INSTALL_PREFIX={ctx.sub(block['install_prefix'])}")
    configure += [ctx.sub(arg) for arg in block.get("args", [])]
    note(f"[{name}] конфигурация")
    run_cmd(ctx, f"build-{name}", configure)

    note(f"[{name}] сборка (-j{ctx.jobs}), это долго")
    compile_cmd = ["cmake", "--build", build_dir, "-j", str(ctx.jobs)]
    if block.get("targets"):
        compile_cmd += ["--target", *block["targets"]]     # собираем только нужные цели, а не всё
    run_cmd(ctx, f"build-{name}", compile_cmd)

    if block.get("install_prefix"):
        run_cmd(ctx, f"build-{name}", ["cmake", "--install", build_dir])


BUILD_SYSTEMS = {"cmake": build_cmake}


def run(ctx):
    say("build: oneTBB и фреймворк")
    for block in ctx.fw["build"]:
        system = block.get("system", "cmake")
        if system not in BUILD_SYSTEMS:
            die(f"[[build]] {block['name']}: система сборки '{system}' не поддерживается "
                f"(есть: {', '.join(BUILD_SYSTEMS)})")
        BUILD_SYSTEMS[system](ctx, block)
        note(f"[{block['name']}] готово")
    mark_done(ctx, NAME)
