"""Офлайн-тесты: ничего не скачивают и не собирают, настоящие cmake/readelf заменены заглушками.

Запуск из корня репозитория:   python3 -m unittest discover -s tests -v
Что проверяется: чтение и проверка конфигов, подстановки, команды cmake, наложение патчей
(в том числе повторное), сборка бандла, проверка verify, генерация и работа run.sh.
Для теста патчей нужен git (в PATH или из work/toolchain/env/bin); без него тест пропускается.
"""
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from rvb.context import Ctx                                  # noqa: E402
from rvb.stages import bootstrap, build, doctor, package, verify   # noqa: E402
from rvb.stages import patch as patch_stage                  # noqa: E402


def write_executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


@contextlib.contextmanager
def quiet():
    """Прячем сообщения этапов, чтобы вывод тестов оставался читаемым."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # копия репозитория: конфиги можно портить, не трогая настоящие
        self.root = self.tmp / "repo"
        for name in ["configs", "templates", "patches"]:
            shutil.copytree(REPO / name, self.root / name)
        (self.root / "models/resnet50").mkdir(parents=True)
        os.environ["RVB_WORK"] = str(self.tmp / "work")
        self.addCleanup(os.environ.pop, "RVB_WORK", None)
        self.ctx = Ctx(self.root, "openvino", "resnet50")


class ConfigTests(Base):
    def test_unknown_placeholder_is_error(self):
        with quiet(), self.assertRaises(SystemExit):
            self.ctx.sub("{instal}/tbb")

    def test_placeholders_are_replaced(self):
        text = self.ctx.sub("{install}/tbb:{sysroot}")
        self.assertEqual(text, f"{self.ctx.install_dir}/tbb:{self.ctx.sysroot}")

    def test_missing_key_is_reported(self):
        toml = self.root / "configs/frameworks/openvino.toml"
        toml.write_text(toml.read_text().replace('repo = "https://github.com/openvinotoolkit/openvino.git"\n', ""))
        with quiet(), self.assertRaises(SystemExit):
            Ctx(self.root, "openvino", "resnet50")

    def test_model_entry_must_be_in_files(self):
        toml = self.root / "configs/models/resnet50.toml"
        toml.write_text(toml.read_text().replace('entry = "resnet-50-pytorch.xml"', 'entry = "other.xml"'))
        with quiet(), self.assertRaises(SystemExit):
            Ctx(self.root, "openvino", "resnet50")


class BuildTests(Base):
    def test_cmake_commands(self):
        log = self.tmp / "cmake.log"
        write_executable(self.ctx.tc / "env/bin/cmake", f'#!/bin/sh\necho "$@" >> {log}\n')
        with quiet():
            build.run(self.ctx)
        lines = log.read_text().splitlines()
        self.assertEqual(len(lines), 5)          # oneTBB: настройка+сборка+установка; OpenVINO: настройка+сборка
        tbb_cfg, tbb_build, tbb_install, ov_cfg, ov_build = lines
        self.assertIn(f"-DCMAKE_TOOLCHAIN_FILE={self.ctx.toolchain_file}", tbb_cfg)
        self.assertIn(f"-DCMAKE_INSTALL_PREFIX={self.ctx.install_dir}/tbb", tbb_cfg)
        self.assertIn("-DTBB_TEST=OFF", tbb_cfg)
        self.assertTrue(tbb_install.startswith("--install"))
        self.assertIn(f"-DCMAKE_FIND_ROOT_PATH={self.ctx.sysroot};{self.ctx.install_dir}/tbb", ov_cfg)
        self.assertIn(f"-DTBB_DIR={self.ctx.install_dir}/tbb/lib/cmake/TBB", ov_cfg)
        self.assertNotIn("CMAKE_INSTALL_PREFIX", ov_cfg)
        self.assertIn("--target openvino_intel_cpu_plugin openvino_ir_frontend benchmark_app", ov_build)

    def test_unknown_build_system(self):
        self.ctx.fw["build"][0]["system"] = "bazel"
        with quiet(), self.assertRaises(SystemExit):
            build.run(self.ctx)


def _git():
    """git из micromamba (если есть) или системный."""
    return shutil.which("git", path=str(Path(os.environ["RVB_WORK"]) / "toolchain/env/bin") + ":" + os.environ["PATH"])


class PatchTests(Base):
    def _make_fake_sources(self):
        """Воссоздаём «чистые» файлы из контекста патчей, чтобы патчи было на что накладывать."""
        openvino = self.ctx.src_dir / "openvino"
        onednn = openvino / "src/plugins/intel_cpu/thirdparty/onednn"
        # Несколько патчей могут править один файл (conv.cpp), поэтому сначала собираем контекст всех
        # патчей по файлам, и только потом пишем каждый файл один раз.
        files = {}                                   # (репозиторий, путь) -> {номер строки: текст}
        for patch_name, base in [("ov_rvv.patch", openvino), ("onednn_rvv.patch", onednn),
                                 ("gemm_ref.patch", openvino)]:
            current, pos = None, 0
            for line in (self.root / "patches/openvino" / patch_name).read_text().split("\n"):
                header = re.match(r"\+\+\+ b/(.*)", line)
                if header:
                    current = (base, header[1])
                    files.setdefault(current, {})
                    continue
                hunk = re.match(r"@@ -(\d+),", line)
                if hunk:
                    pos = int(hunk[1])
                    continue
                if current and line[:1] in (" ", "-") and not line.startswith("---"):
                    files[current][pos] = line[1:]
                    pos += 1
        for (base, rel), lines in files.items():
            content = [f"filler {i}" for i in range(1, max(lines) + 20)]
            for number, text in lines.items():
                content[number - 1] = text
            target = base / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(content) + "\n")
        for repo in (onednn, openvino):          # у подмодуля свой git, как в настоящем OpenVINO
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"],
                           cwd=repo, check=True)
        return openvino, onednn

    def test_apply_and_reapply(self):
        if shutil.which("git") is None:
            self.skipTest("нет git")
        openvino, onednn = self._make_fake_sources()
        with quiet():
            patch_stage.run(self.ctx)
            patch_stage.run(self.ctx)            # повторный запуск не должен ломаться
        conv = (openvino / "src/plugins/intel_cpu/src/nodes/conv.cpp").read_text()
        self.assertIn("impl_desc_type::brgemm", conv)                 # ov_rvv.patch
        self.assertIn("impl_desc_type::gemm_ref", conv)               # gemm_ref.patch поверх него в том же файле
        mapper = (openvino / "src/plugins/intel_cpu/src/onednn/iml_type_mapper.h").read_text()
        self.assertIn("gemm_ref = gemm | ref", mapper)
        convolution_list = (onednn / "src/cpu/cpu_convolution_list.cpp").read_text()
        self.assertIn("CPU_INSTANCE_RV64(rvv_brgemm_convolution_fwd_t)", convolution_list)

    def test_patch_that_does_not_fit_stops(self):
        if shutil.which("git") is None:
            self.skipTest("нет git")
        openvino, _ = self._make_fake_sources()
        (openvino / "src/plugins/intel_cpu/src/nodes/conv.cpp").write_text("совсем другой файл\n")
        with quiet(), self.assertRaises(SystemExit):
            patch_stage.run(self.ctx)


READELF_STUB = """#!/bin/sh
case "$1" in
  -h) echo "  Machine:                           RISC-V" ;;
  -d) echo " 0x0000000000000001 (NEEDED)             Shared library: [libtbb.so.12]"
      echo " 0x0000000000000001 (NEEDED)             Shared library: [libc.so.6]" ;;
esac
"""

BENCH_STUB = """#!/bin/sh
echo "$@" > "$(dirname "$0")/../last_args.txt"
echo "[ INFO ] Latency:"
echo "[ INFO ]    Median:           51114.67 ms"
echo "[ INFO ]    Average:          51200.10 ms"
echo "[ INFO ]    Min:              51000.00 ms"
echo "[ INFO ]    Max:              51300.50 ms"
echo "[ INFO ] Throughput:          0.02 FPS"
"""


class NetworkTests(Base):
    """Сеть может отвечать медленно: это не должно останавливать сборку."""

    class _Response:
        def __init__(self, data):
            self.data = data

        def read(self, *_):
            return self.data

    def test_doctor_network_failure_is_only_a_warning(self):
        out = io.StringIO()
        with mock.patch("urllib.request.urlopen", side_effect=OSError("timed out")), \
                mock.patch.object(doctor, "NETWORK_ATTEMPTS", 1), contextlib.redirect_stdout(out):
            doctor._check_network(self.ctx)                 # не должно завершать скрипт
        self.assertIn("[??] сеть", out.getvalue())
        self.assertNotIn("[!!]", out.getvalue())

    def test_download_retries_then_succeeds(self):
        answers = [OSError("t1"), OSError("t2"), self._Response(b"data")]
        with mock.patch("urllib.request.urlopen", side_effect=answers) as urlopen, \
                mock.patch("time.sleep"), quiet():
            data = bootstrap._download("https://example.invalid/x", "x")
        self.assertEqual(data, b"data")
        self.assertEqual(urlopen.call_count, 3)

    def test_download_gives_up_with_clear_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("timed out")), \
                mock.patch("time.sleep"), quiet(), self.assertRaises(SystemExit):
            bootstrap._download("https://example.invalid/x", "x")


class BundleTests(Base):
    """package -> verify -> run.sh на заглушках."""

    def setUp(self):
        super().setUp()
        release = self.ctx.src_dir / "openvino/bin/riscv64/Release"
        tbb_lib = self.ctx.install_dir / "tbb/lib"
        release.mkdir(parents=True)
        tbb_lib.mkdir(parents=True)
        (release / "benchmark_app").write_text("bin")
        (release / "libopenvino.so.2026.4.0").write_text("lib")
        (release / "libopenvino.so.2640").symlink_to("libopenvino.so.2026.4.0")
        (release / "libopenvino.so").symlink_to("libopenvino.so.2640")
        (release / "libopenvino_ir_frontend.so").write_text("ir")
        (release / "libopenvino_riscv_cpu_plugin.so").write_text("... convolution_dnnl_rvv_nspc ... rvv_brgemm ... gemm_ref ...")
        (release / "libopenvino_onednn_cpu.a").write_text("не должен попасть в бандл")
        (tbb_lib / "libtbb.so.12.17").write_text("tbb")
        (tbb_lib / "libtbb.so.12").symlink_to("libtbb.so.12.17")
        (tbb_lib / "libtbb.so").symlink_to("libtbb.so.12")
        (tbb_lib / "libtbbmalloc.so.2").write_text("m")
        (tbb_lib / "libtbbmalloc_proxy.so.2").write_text("p")
        (self.root / "models/resnet50/resnet-50-pytorch.xml").write_text("<xml/>")
        (self.root / "models/resnet50/resnet-50-pytorch.bin").write_text("weights")
        write_executable(self.ctx.sysroot / "usr/bin/riscv64-linux-gnu-readelf", READELF_STUB)
        # нужны git_head() для MANIFEST: пусть вернёт «?», это допустимо
        with quiet():
            package.run(self.ctx)

    def test_bundle_layout(self):
        out = self.ctx.out
        self.assertTrue((out / "bin/libopenvino.so").is_symlink())        # ссылки сохранены
        self.assertEqual(os.readlink(out / "bin/libopenvino.so"), "libopenvino.so.2640")
        self.assertFalse((out / "bin/libopenvino_onednn_cpu.a").exists())  # лишнее не попало
        self.assertTrue((out / "model/resnet-50-pytorch.bin").exists())
        self.assertTrue((out / "MANIFEST.txt").exists())
        self.assertTrue(out.with_suffix(".tar.gz").exists())
        script = (out / "run.sh").read_text()
        self.assertIsNone(re.search(r"@@[A-Z_]+@@", script))               # все метки подставлены
        self.assertIn('-nthreads "$threads"', script)
        self.assertIn('-b "$batch"', script)
        subprocess.run(["bash", "-n", str(out / "run.sh")], check=True)    # синтаксис bash

    def test_verify_ok(self):
        with quiet():
            verify.run(self.ctx)

    def test_verify_detects_missing_patch_string(self):
        (self.ctx.out / "bin/libopenvino_riscv_cpu_plugin.so").write_text("без патчей")
        with quiet(), self.assertRaises(SystemExit):
            verify.run(self.ctx)

    def test_verify_detects_missing_dependency(self):
        for lib in (self.ctx.out / "tbb").glob("libtbb.so*"):
            lib.unlink()
        with quiet(), self.assertRaises(SystemExit):
            verify.run(self.ctx)

    def test_package_without_model_fails(self):
        (self.root / "models/resnet50/resnet-50-pytorch.bin").unlink()
        with quiet(), self.assertRaises(SystemExit):
            package.run(self.ctx)

    def _run_sh(self, *args, **extra_env):
        """Запустить run.sh с заглушками benchmark_app и taskset; вернуть (строки CSV, аргументы taskset, аргументы бенча)."""
        out = self.ctx.out
        write_executable(out / "bin/benchmark_app", BENCH_STUB)
        # Настоящий taskset на общем сервере может отказать (нужных ядер нет в разрешённых),
        # поэтому подставляем заглушку: она записывает "-c <ядра>" и запускает остальное.
        fake_bin = out / "fake_bin"
        write_executable(fake_bin / "taskset", '#!/bin/sh\necho "$2" >> "$(dirname "$0")/../cpus.txt"\nshift 2\nexec "$@"\n')
        env = dict(os.environ, NITER="1", DURATION="1", PATH=f"{fake_bin}:{os.environ['PATH']}", **extra_env)
        subprocess.run(["bash", str(out / "run.sh"), *args], env=env, check=True, capture_output=True)
        csv_files = list((out / "results").glob("*/results.csv"))
        self.assertEqual(len(csv_files), 1)
        return csv_files[0].read_text().splitlines(), (out / "cpus.txt").read_text().split()

    def test_run_script_latency(self):
        rows, cpus = self._run_sh("latency", "1", "2")
        self.assertEqual(rows[0], "scenario,value,cores,median_ms,avg_ms,min_ms,max_ms,fps")
        self.assertEqual(rows[1], "latency,1,0-0,51114.67,51200.10,51000.00,51300.50,0.02")
        self.assertEqual(rows[2], "latency,2,0-1,51114.67,51200.10,51000.00,51300.50,0.02")
        self.assertEqual(cpus, ["0-0", "0-1"])
        args = (self.ctx.out / "last_args.txt").read_text()
        for part in ("-api sync", "-b 1", "-nthreads 2", "-niter 1", "-report_type no_counters",
                     "-m " + str(self.ctx.out / "model/resnet-50-pytorch.xml")):
            self.assertIn(part, args)

    def test_run_script_short_form_means_latency(self):
        rows, _ = self._run_sh("2")                    # старый вид: ./run.sh 2
        self.assertTrue(rows[1].startswith("latency,2,0-1,"))

    def test_run_script_throughput_on_a100(self):
        rows, cpus = self._run_sh("throughput", "2", "4", CORES="a100")
        self.assertEqual([r.split(",")[:3] for r in rows[1:]],
                         [["throughput", "2", "8-15"], ["throughput", "4", "8-15"]])
        self.assertEqual(cpus, ["8-15", "8-15"])
        args = (self.ctx.out / "last_args.txt").read_text()
        for part in ("-api async", "-b 4", "-nthreads 8", "-nstreams 8", "-nireq 8", "-t 1"):
            self.assertIn(part, args)
        self.assertTrue(list((self.ctx.out / "results").glob("*/report_throughput_4")))

    def test_run_script_latency_on_a100_starts_at_core_8(self):
        _, cpus = self._run_sh("latency", "4", CORES="a100")
        self.assertEqual(cpus, ["8-11"])

    def test_run_script_all_scenarios_by_default(self):
        rows, _ = self._run_sh()
        names = [r.split(",")[0] for r in rows[1:]]
        self.assertEqual(names, ["latency"] * 4 + ["throughput"] * 6)


if __name__ == "__main__":
    unittest.main()
