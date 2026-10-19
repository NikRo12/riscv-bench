"""riscv-bench: кросс-сборка ML-фреймворка для RISC-V платы и упаковка в папку-бандл.

Устройство пакета:
    config.py    - чтение и проверка TOML-конфигов
    context.py   - Ctx: все пути, конфиги и подстановки {work}, {src}... в одном объекте
    runner.py    - запуск внешних команд с записью вывода в лог
    stamps.py    - метки «этап уже выполнен»
    toolchain.py - генерация CMake toolchain-файла для кросс-компиляции
    gitutil.py   - мелкие вызовы git
    manifest.py  - MANIFEST.txt (паспорт бандла)
    util.py      - say/note/die, sha256
    stages/      - по одному файлу на этап: doctor, bootstrap, fetch, patch, build, package, verify
"""
