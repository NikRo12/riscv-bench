"""Ctx - один объект со всем, что нужно этапам: конфиги, пути, подстановки, окружение.

Этапы получают ctx первым аргументом и ничего не читают из глобальных переменных.
Это упрощает тесты: можно создать Ctx с другой рабочей папкой.
"""
import os
import re
from pathlib import Path

from .config import load_toml, validate_framework, validate_model, validate_target
from .util import die


class Ctx:
    def __init__(self, root, framework, model, jobs=0, force=False):
        self.root = Path(root).resolve()                      # корень репозитория
        self.work = Path(os.environ.get("RVB_WORK", self.root / "work"))
        self.framework = framework
        self.model_name = model
        self.force = force
        self.jobs = jobs or os.cpu_count() or 4

        # --- конфиги
        self.target = load_toml(self.root / "configs/target.toml")
        validate_target(self.target)
        fw_file = f"configs/frameworks/{framework}.toml"
        self.fw = load_toml(self.root / fw_file)
        validate_framework(self.fw, fw_file)
        model_file = f"configs/models/{model}.toml"
        self.model = load_toml(self.root / model_file)
        validate_model(self.model, model_file)

        # --- сокращения для частых разделов
        self.board = self.target["board"]
        self.toolchain = self.target["toolchain"]
        self.host = self.target["host"]

        # --- пути внутри рабочей папки (всё, что создаётся при работе, лежит в work/)
        self.src_dir = self.work / "src"             # исходники фреймворков
        self.build_dir = self.work / "build"         # каталоги сборки
        self.install_dir = self.work / "install"     # результаты `cmake --install`
        self.tc = self.work / "toolchain"            # micromamba, deb-пакеты, sysroot
        self.sysroot = self.tc / "root"              # libc и заголовки для RISC-V
        self.logs = self.work / "logs"
        self.stamps = self.work / "stamps"
        self.toolchain_file = self.work / "riscv64.toolchain.cmake"

        # --- результат
        self.out = self.root / "out" / f"{framework}-{model}"

    # ------------------------------------------------------------ подстановки
    def placeholders(self):
        """Что можно писать в фигурных скобках в путях и аргументах из TOML."""
        return {
            "work": self.work, "src": self.src_dir, "build": self.build_dir,
            "install": self.install_dir, "sysroot": self.sysroot,
            "toolchain_file": self.toolchain_file, "jobs": self.jobs,
        }

    def sub(self, text):
        """Заменить {work}, {src}, {build}, {install}, {sysroot}, {toolchain_file}, {jobs}.

        Неизвестная подстановка (например, опечатка {instal}) - ошибка, а не молчаливый мусор в пути.
        """
        for key, value in self.placeholders().items():
            text = text.replace("{" + key + "}", str(value))
        unknown = re.findall(r"\{[A-Za-z_]+\}", text)
        if unknown:
            die(f"неизвестная подстановка {unknown[0]} в «{text}». "
                f"Доступны: {', '.join('{' + k + '}' for k in self.placeholders())}")
        return text

    # ------------------------------------------------------------ окружение
    def env(self):
        """Окружение для внешних команд.

        В PATH первыми идут наши cmake/ninja/git (micromamba) и кросс-GCC из sysroot,
        в LD_LIBRARY_PATH - x86-библиотеки, без которых сам кросс-компилятор не запускается.
        Так всё работает без root и не трогает систему.
        """
        env = os.environ.copy()
        bins = [self.tc / "env/bin", self.sysroot / "usr/bin"]
        libs = [self.tc / "host/usr/lib/x86_64-linux-gnu",
                self.tc / "host/lib/x86_64-linux-gnu",
                self.sysroot / "usr/lib/x86_64-linux-gnu"]
        env["PATH"] = ":".join(map(str, bins)) + ":" + env.get("PATH", "")
        old = env.get("LD_LIBRARY_PATH")
        env["LD_LIBRARY_PATH"] = ":".join(map(str, libs)) + (":" + old if old else "")
        return env
