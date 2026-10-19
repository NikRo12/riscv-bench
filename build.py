#!/usr/bin/env python3
"""Кросс-сборка фреймворка для RISC-V платы и упаковка в папку-бандл.

Запуск:  python3 build.py <этап> [--framework openvino] [--model resnet50] [--jobs N] [--force]
Этапы:   doctor bootstrap fetch patch build package verify all
Без root: всё ставится в ./work (кросс-GCC, cmake, ninja, исходники, сборка).
Готовый результат: ./out/<framework>-<model>/  и  ./out/<framework>-<model>.tar.gz
"""
import argparse, fnmatch, glob, hashlib, io, os, shutil, subprocess, sys, tarfile, time, tomllib
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = Path(os.environ.get("RVB_WORK", ROOT / "work"))
STAGES = ["doctor", "bootstrap", "fetch", "patch", "build", "package", "verify"]
TTY = sys.stdout.isatty()
MICROMAMBA_URL = "https://micro.mamba.pm/api/micromamba/linux-64/latest"


def say(msg):
    print(f"\n=== {msg}", flush=True)


def die(msg):
    print(f"\nОШИБКА: {msg}", file=sys.stderr)
    sys.exit(1)


def load_toml(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


class Ctx:
    """Все пути и настройки одним объектом."""

    def __init__(self, args):
        self.args = args
        self.target = load_toml(ROOT / "configs/target.toml")
        self.fw = load_toml(ROOT / f"configs/frameworks/{args.framework}.toml")
        self.model = load_toml(ROOT / f"configs/models/{args.model}.toml")
        self.fw_name = args.framework
        self.tc = WORK / "toolchain"
        self.sysroot = self.tc / "root"
        self.logs = WORK / "logs"
        self.stamps = WORK / "stamps"
        self.toolchain_file = WORK / "riscv64.toolchain.cmake"
        self.tbb_prefix = WORK / "install/tbb"
        self.jobs = args.jobs or os.cpu_count() or 4
        self.out = ROOT / "out" / f"{args.framework}-{args.model}"

    def sub(self, s):
        return (s.replace("{work}", str(WORK)).replace("{sysroot}", str(self.sysroot))
                 .replace("{toolchain_file}", str(self.toolchain_file))
                 .replace("{tbb_prefix}", str(self.tbb_prefix)).replace("{jobs}", str(self.jobs)))

    def env(self):
        """Окружение для запуска утилит: наши cmake/ninja/git и кросс-GCC без root."""
        e = os.environ.copy()
        bins = [self.tc / "env/bin", self.sysroot / "usr/bin"]
        libs = [self.tc / "host/usr/lib/x86_64-linux-gnu", self.tc / "host/lib/x86_64-linux-gnu",
                self.sysroot / "usr/lib/x86_64-linux-gnu"]
        e["PATH"] = ":".join(str(p) for p in bins) + ":" + e["PATH"]
        e["LD_LIBRARY_PATH"] = ":".join(str(p) for p in libs) + (":" + e["LD_LIBRARY_PATH"] if e.get("LD_LIBRARY_PATH") else "")
        return e


def run(ctx, stage, cmd, cwd=None, check=True):
    """Запуск команды: весь вывод в work/logs/<stage>.log, на экран - последние строки."""
    ctx.logs.mkdir(parents=True, exist_ok=True)
    log = ctx.logs / f"{stage}.log"
    printable = " ".join(str(c) for c in cmd)
    with open(log, "a") as lf:
        lf.write(f"\n$ {printable}   (cwd={cwd})\n")
        lf.flush()
        p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=ctx.env(), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, errors="replace")
        last = ""
        for line in p.stdout:
            lf.write(line)
            last = line.rstrip()
            if TTY:
                print("\r\x1b[K" + last[:110], end="", flush=True)
        p.wait()
        if TTY:
            print("\r\x1b[K", end="")
    if check and p.returncode != 0:
        die(f"команда упала (код {p.returncode}): {printable[:200]}\nЛог: {log}")
    return p.returncode


def stamp(ctx, stage):
    return ctx.stamps / f"{ctx.fw_name}.{stage}"


def done(ctx, stage):
    return stamp(ctx, stage).exists() and not ctx.args.force


def mark(ctx, stage):
    ctx.stamps.mkdir(parents=True, exist_ok=True)
    stamp(ctx, stage).write_text(time.strftime("%F %T\n"))


# ---------------------------------------------------------------- doctor
def st_doctor(ctx):
    say("doctor: проверка сервера")
    ok = True
    if sys.version_info < (3, 11):
        print("  [!] нужен Python >= 3.11 (tomllib)"); ok = False
    for tool in ["apt", "dpkg", "tar"]:
        found = shutil.which(tool)
        print(f"  [{'ok' if found else '!!'}] {tool}")
        ok &= bool(found)
    WORK.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(WORK).free / 2**30
    mark_ = "ok" if free >= 12 else ("??" if free >= 8 else "!!")
    print(f"  [{mark_}] свободно {free:.0f} ГБ (нужно ~7, комфортно >= 12)")
    if 8 <= free < 12:
        print("      предупреждение: места впритык, следите за df -h во время сборки")
    ok &= free >= 8
    print(f"  [ok] ядер: {os.cpu_count()}")
    for url in [MICROMAMBA_URL, "https://github.com"]:
        try:
            req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
            urllib.request.urlopen(req, timeout=15).read(1)
            print(f"  [ok] сеть: {url}")
        except urllib.error.HTTPError as ex:
            print(f"  [ok] сеть: {url} (ответ HTTP {ex.code})")
        except Exception as ex:
            print(f"  [!!] сеть: {url} ({ex})"); ok = False
    if not ok:
        die("doctor нашёл проблемы (см. [!!])")


# ---------------------------------------------------------------- bootstrap
def st_bootstrap(ctx):
    say("bootstrap: cmake/ninja/git (micromamba) и кросс-GCC (deb без root)")
    tc = ctx.tc
    for d in ["mm", "debs", "host_debs", "host", "root"]:
        (tc / d).mkdir(parents=True, exist_ok=True)
    mm = tc / "mm/bin/micromamba"
    if not mm.exists():
        print("  скачиваю micromamba")
        data = urllib.request.urlopen(MICROMAMBA_URL, timeout=120).read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:bz2") as t:
            t.extractall(tc / "mm", filter="data")
    if not (tc / "env/bin/cmake").exists():
        env = ctx.env()
        env["MAMBA_ROOT_PREFIX"] = str(tc / "mm/root")
        pk = ctx.target["toolchain"]["conda_packages"]
        run_env(ctx, "bootstrap", [mm, "create", "-y", "-p", tc / "env", "-c", "conda-forge", *pk], env)
    for key, dd, dest in [("cross_debs", "debs", "root"), ("host_debs", "host_debs", "host")]:
        names = ctx.target["toolchain"][key]
        have = {Path(p).name.split("_")[0] for p in glob.glob(str(tc / dd / "*.deb"))}
        missing = [n for n in names if n not in have]
        if missing:
            run(ctx, "bootstrap", ["apt", "download", *missing], cwd=tc / dd)
        for deb in sorted(glob.glob(str(tc / dd / "*.deb"))):
            run(ctx, "bootstrap", ["dpkg", "-x", deb, tc / dest])
    write_toolchain_file(ctx)
    # проверка: кросс-компилятор запускается и собирает программу с нужным -march
    t = WORK / "tc_test"; t.mkdir(exist_ok=True)
    (t / "t.c").write_text("int main(void){return 0;}\n")
    cc = ctx.target["toolchain"]["cc"]
    run(ctx, "bootstrap", [cc, f"-march={ctx.target['board']['arch']}", f"-mabi={ctx.target['board']['abi']}",
                           f"--sysroot={ctx.sysroot}", "-O2", t / "t.c", "-o", t / "t"])
    print("  кросс-компилятор работает")
    mark(ctx, "bootstrap")


def run_env(ctx, stage, cmd, env):
    log = ctx.logs / f"{stage}.log"
    ctx.logs.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as lf:
        r = subprocess.run([str(c) for c in cmd], env=env, stdout=lf, stderr=subprocess.STDOUT)
    if r.returncode:
        die(f"упало: {cmd[0]}. Лог: {log}")


def write_toolchain_file(ctx):
    b, t = ctx.target["board"], ctx.target["toolchain"]
    common = f"-march={b['arch']} -mabi={b['abi']} -mtune={b['tune']}"
    ctx.toolchain_file.write_text(f"""# Сгенерировано build.py из configs/target.toml - руками не править
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR riscv64)
set(CMAKE_SYSROOT "{ctx.sysroot}")
set(CMAKE_C_COMPILER   {t['cc']})
set(CMAKE_CXX_COMPILER {t['cxx']})
set(CMAKE_C_FLAGS_INIT   "{common}")
set(CMAKE_CXX_FLAGS_INIT "{common}")
set(CMAKE_FIND_ROOT_PATH "{ctx.sysroot}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE BOTH)
""")


# ---------------------------------------------------------------- fetch
def st_fetch(ctx):
    say("fetch: исходники")
    s = ctx.fw["source"]
    items = [(s["name"], s["repo"], s["version"], s.get("submodules", False))]
    items += [(d["name"], d["repo"], d["version"], False) for d in ctx.fw.get("deps", [])]
    for name, repo, ver, subs in items:
        dst = WORK / "src" / name
        if (dst / ".git").exists():
            print(f"  {name}: уже есть")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        run(ctx, "fetch", ["git", "clone", "--branch", ver, "--depth", "1", repo, dst])
        if subs:
            run(ctx, "fetch", ["git", "submodule", "update", "--init", "--recursive", "--depth", "1", "--jobs", "8"], cwd=dst)
        print(f"  {name} {ver}: ok")
    mark(ctx, "fetch")


# ---------------------------------------------------------------- patch
def st_patch(ctx):
    say("patch: применение патчей (git apply --check перед применением)")
    src = WORK / "src" / ctx.fw["source"]["name"]
    for p in ctx.fw.get("patches", []):
        pf = ROOT / "patches" / ctx.fw_name / p["file"]
        d = (src / p["dir"]).resolve()
        if run(ctx, "patch", ["git", "-C", d, "apply", "--check", pf], check=False) == 0:
            run(ctx, "patch", ["git", "-C", d, "apply", pf])
            print(f"  применён: {p['file']}")
        elif run(ctx, "patch", ["git", "-C", d, "apply", "--check", "-R", pf], check=False) == 0:
            print(f"  уже применён: {p['file']}")
        else:
            die(f"патч {p['file']} не ложится на исходники (версия изменилась?). Лог: {ctx.logs/'patch.log'}")
    mark(ctx, "patch")


# ---------------------------------------------------------------- build
def st_build(ctx):
    say("build: oneTBB и фреймворк")
    for b in ctx.fw["build"]:
        name, bdir, srcd = b["name"], Path(ctx.sub(b["build_dir"])), ctx.sub(b["source"])
        print(f"  [{name}] конфигурация")
        cmd = ["cmake", "-S", srcd, "-B", bdir, "-G", "Ninja", f"-DCMAKE_TOOLCHAIN_FILE={ctx.toolchain_file}",
               "-DCMAKE_BUILD_TYPE=Release"]
        if b.get("install_prefix"):
            cmd.append(f"-DCMAKE_INSTALL_PREFIX={ctx.sub(b['install_prefix'])}")
        cmd += [ctx.sub(a) for a in b.get("args", [])]
        run(ctx, f"build-{name}", cmd)
        print(f"  [{name}] сборка (-j{ctx.jobs}), это долго")
        bc = ["cmake", "--build", bdir, "-j", str(ctx.jobs)]
        if b.get("targets"):
            bc += ["--target", *b["targets"]]
        run(ctx, f"build-{name}", bc)
        if b.get("install_prefix"):
            run(ctx, f"build-{name}", ["cmake", "--install", bdir])
        print(f"  [{name}] готово")
    mark(ctx, "build")


# ---------------------------------------------------------------- package
def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head(ctx, d):
    r = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], env=ctx.env(), capture_output=True, text=True)
    return r.stdout.strip() or "?"


def st_package(ctx):
    say("package: сборка папки для платы")
    out = ctx.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for b in ctx.fw["bundle"]:
        src, dest = Path(ctx.sub(b["src"])), out / b["dest"]
        dest.mkdir(parents=True, exist_ok=True)
        for pat in b["patterns"]:
            hits = [f for f in src.iterdir() if fnmatch.fnmatch(f.name, pat)]
            if not hits:
                die(f"в {src} нет файлов по маске {pat}")
            for f in hits:
                t = dest / f.name
                if f.is_symlink():
                    os.symlink(os.readlink(f), t)   # симлинки сохраняем как есть
                else:
                    shutil.copy2(f, t)
    mpath = ROOT / ctx.model["path"]
    if not mpath.exists():
        die(f"нет модели {mpath}. Скопируйте .xml и .bin с платы в {mpath.parent}/")
    (out / "model").mkdir()
    for ext in (".xml", ".bin"):
        f = mpath.with_suffix(ext)
        if not f.exists():
            die(f"нет {f}")
        shutil.copy2(f, out / "model" / f.name)
    tpl = (ROOT / "templates/run.sh").read_text()
    tpl = tpl.replace("@@BENCH@@", ctx.fw["run"]["benchmark"]).replace("@@MODEL@@", f"model/{mpath.name}")
    (out / "run.sh").write_text(tpl)
    (out / "run.sh").chmod(0o755)
    write_manifest(ctx, out)
    arc = out.with_suffix(".tar.gz")
    with tarfile.open(arc, "w:gz") as t:
        t.add(out, arcname=out.name)
    print(f"  папка: {out}\n  архив: {arc} ({arc.stat().st_size/2**20:.0f} МБ)")
    mark(ctx, "package")


def write_manifest(ctx, out):
    s = ctx.fw["source"]
    L = [f"bundle: {ctx.fw_name} + {ctx.args.model}", f"built: {time.strftime('%F %T')}",
         f"board: {ctx.target['board']['name']}", f"march: {ctx.target['board']['arch']}",
         f"mtune: {ctx.target['board']['tune']}", "", "[sources]",
         f"{s['name']} {s['version']} commit {git_head(ctx, WORK/'src'/s['name'])}"]
    for d in ctx.fw.get("deps", []):
        L.append(f"{d['name']} {d['version']} commit {git_head(ctx, WORK/'src'/d['name'])}")
    L += ["", "[patches] (правки сняты с платы, происхождение не подтверждено автором)"]
    for p in ctx.fw.get("patches", []):
        pf = ROOT / "patches" / ctx.fw_name / p["file"]
        L.append(f"{p['file']} sha256 {sha256(pf)[:16]}  {p['note']}")
    L += ["", "[files] sha256(16) size name"]
    for f in sorted(out.rglob("*")):
        if f.is_file() and not f.is_symlink() and f.name != "MANIFEST.txt":
            L.append(f"{sha256(f)[:16]} {f.stat().st_size:>10} {f.relative_to(out)}")
    (out / "MANIFEST.txt").write_text("\n".join(L) + "\n")


# ---------------------------------------------------------------- verify
def st_verify(ctx):
    say("verify: проверка бандла (на сервере, без запуска)")
    out, ok = ctx.out, True
    readelf = ctx.target["toolchain"]["readelf"]
    bench = out / "bin" / ctx.fw["run"]["benchmark"]
    plugin = out / "bin/libopenvino_riscv_cpu_plugin.so"
    for f in [bench, plugin, out / "bin/libopenvino.so"]:
        r = subprocess.run([readelf, "-h", str(f)], env=ctx.env(), capture_output=True, text=True)
        good = "RISC-V" in r.stdout
        print(f"  [{'ok' if good else '!!'}] архитектура RISC-V: {f.name}")
        ok &= good
    # все ли NEEDED-библиотеки лежат в бандле (кроме системных libc/libstdc++/libgcc/libm/ld)
    sysnames = ("libc.so", "libm.so", "libstdc++", "libgcc_s", "ld-linux", "libpthread", "libdl", "librt", "libgomp")
    have = {p.name for p in out.rglob("*")}
    for f in [bench, plugin, out / "bin/libopenvino.so"]:
        r = subprocess.run([readelf, "-d", str(f)], env=ctx.env(), capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if "(NEEDED)" in line:
                lib = line.split("[")[1].split("]")[0]
                if lib not in have and not lib.startswith(sysnames):
                    print(f"  [!!] {f.name} требует {lib}, его нет в бандле"); ok = False
    # доказательство, что патчи попали в бинарник плагина
    blob = plugin.read_bytes()
    for needle in [b"convolution_dnnl_rvv_nspc", b"rvv_brgemm"]:
        hit = needle in blob
        print(f"  [{'ok' if hit else '!!'}] в плагине есть '{needle.decode()}'")
        ok &= hit
    for rel in ["run.sh", "MANIFEST.txt", "model"]:
        print(f"  [{'ok' if (out/rel).exists() else '!!'}] {rel}")
        ok &= (out / rel).exists()
    if not ok:
        die("verify: есть проблемы (см. [!!])")
    print("\nГотово. Перенос на плату: scp -r или tar.gz из out/")
    mark(ctx, "verify")


FUNCS = {"doctor": st_doctor, "bootstrap": st_bootstrap, "fetch": st_fetch, "patch": st_patch,
         "build": st_build, "package": st_package, "verify": st_verify}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=STAGES + ["all"])
    ap.add_argument("--framework", default="openvino")
    ap.add_argument("--model", default="resnet50")
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="повторить этап, даже если он уже выполнялся")
    args = ap.parse_args()
    ctx = Ctx(args)
    stages = STAGES if args.stage == "all" else [args.stage]
    for s in stages:
        if args.stage == "all" and s in ("bootstrap", "fetch", "patch", "build") and done(ctx, s):
            print(f"\n=== {s}: пропуск (уже сделан, --force чтобы повторить)")
            continue
        FUNCS[s](ctx)


if __name__ == "__main__":
    main()
