# riscv-bench

Кросс-сборка OpenVINO (+oneTBB) для SpacemiT K3 и готовая папка для платы.

## На сервере
    cp /путь/к/resnet-50-pytorch.{xml,bin} models/resnet50/   # модель (скопировать с платы)
    python3 build.py doctor      # проверка сервера
    python3 build.py all         # bootstrap -> fetch -> patch -> build -> package -> verify
Этапы можно запускать по одному (`bootstrap`, `fetch`, `patch`, `build`, `package`, `verify`).
Повторить этап: `--force`. Логи: `work/logs/<этап>.log`.

Результат: `out/openvino-resnet50/` и `out/openvino-resnet50.tar.gz`.

## На плате
    tar xzf openvino-resnet50.tar.gz && cd openvino-resnet50
    ./run.sh            # потоки 1 2 4 8, NITER=5;  ./run.sh 8  /  NITER=1 ./run.sh 8
Результаты: `results/<время>/results.csv`.
