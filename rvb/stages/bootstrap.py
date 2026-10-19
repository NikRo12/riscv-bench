"""Этап bootstrap: поставить инструменты сборки и кросс-компилятор без root.

Всё ставится в work/toolchain:
    mm/         micromamba (менеджер пакетов, один исполняемый файл)
    env/        cmake, ninja, git, make, curl из conda-forge
    debs/       скачанные .deb кросс-GCC (apt download, root не нужен)
    root/       они же, распакованные (dpkg -x); это и есть sysroot для RISC-V
    host_debs/, host/   x86-библиотеки, без которых не запускается сам кросс-компилятор
"""
import glob
import io
import tarfile
import urllib.request
from pathlib import Path

from ..runner import run as run_cmd
from ..stamps import mark_done
from ..toolchain import write_toolchain_file
from ..util import note, say

NAME = "bootstrap"
HELP = "поставить cmake/ninja/git (micromamba) и кросс-GCC (.deb без root)"
SKIP_IF_DONE = True


def _ensure_micromamba(ctx):
    micromamba = ctx.tc / "mm/bin/micromamba"
    if micromamba.exists():
        return micromamba
    note("скачиваю micromamba")
    data = urllib.request.urlopen(ctx.toolchain["micromamba_url"], timeout=120).read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:bz2") as archive:
        archive.extractall(ctx.tc / "mm", filter="data")   # filter="data": не даём архиву писать за пределы папки
    return micromamba


def _ensure_conda_env(ctx, micromamba):
    """cmake, ninja, git... в work/toolchain/env (канал и список пакетов - в target.toml)."""
    if (ctx.tc / "env/bin/cmake").exists():
        return
    note("ставлю cmake/ninja/git через micromamba")
    env = ctx.env()
    env["MAMBA_ROOT_PREFIX"] = str(ctx.tc / "mm/root")    # кэш micromamba тоже держим внутри work/
    run_cmd(ctx, "bootstrap",
            [micromamba, "create", "-y", "-p", ctx.tc / "env", "-c", ctx.toolchain["conda_channel"],
             *ctx.toolchain["conda_packages"]], env=env)


def _ensure_debs(ctx, package_names, download_dir, extract_dir):
    """Скачать недостающие .deb (apt download) и распаковать их (dpkg -x) - всё без root."""
    download_dir.mkdir(parents=True, exist_ok=True)
    have = {Path(p).name.split("_")[0] for p in glob.glob(str(download_dir / "*.deb"))}
    missing = [name for name in package_names if name not in have]
    if missing:
        note(f"скачиваю {len(missing)} deb-пакетов")
        run_cmd(ctx, "bootstrap", ["apt", "download", *missing], cwd=download_dir)
    for deb in sorted(glob.glob(str(download_dir / "*.deb"))):
        run_cmd(ctx, "bootstrap", ["dpkg", "-x", deb, extract_dir])


def _selftest_compiler(ctx):
    """Собрать пустую программу: если не получилось, ломаться лучше сейчас, а не через час сборки."""
    test_dir = ctx.work / "tc_test"
    test_dir.mkdir(parents=True, exist_ok=True)
    source = test_dir / "t.c"
    source.write_text("int main(void){return 0;}\n")
    run_cmd(ctx, "bootstrap",
            [ctx.toolchain["cc"], f"-march={ctx.board['arch']}", f"-mabi={ctx.board['abi']}",
             f"--sysroot={ctx.sysroot}", "-O2", source, "-o", test_dir / "t"])
    note("кросс-компилятор работает")


def run(ctx):
    say("bootstrap: cmake/ninja/git (micromamba) и кросс-GCC (deb без root)")
    micromamba = _ensure_micromamba(ctx)
    _ensure_conda_env(ctx, micromamba)
    _ensure_debs(ctx, ctx.toolchain["cross_debs"], ctx.tc / "debs", ctx.tc / "root")
    _ensure_debs(ctx, ctx.toolchain["host_debs"], ctx.tc / "host_debs", ctx.tc / "host")
    write_toolchain_file(ctx)
    _selftest_compiler(ctx)
    mark_done(ctx, NAME)
