#!/usr/bin/env bash
# Замер скорости на плате. Лежит в корне бандла рядом с bin/, tbb/, model/.
#
# Использование:  ./run.sh [потоки...]       например  ./run.sh 1 4 8   (по умолчанию 1 2 4 8)
# Переменные:     NITER=5        число итераций бенчмарка
#                 MODEL=путь     другая модель вместо model/...
#
# Файл сгенерирован build.py из templates/run.sh: слова между @@ подставляются из конфига фреймворка
# (раздел [run]). Править лучше конфиг и шаблон, а не готовый run.sh.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH="$HERE/@@BENCH@@"
MODEL="${MODEL:-$HERE/@@MODEL@@}"
NITER="${NITER:-5}"
THREADS=("$@"); [ ${#THREADS[@]} -eq 0 ] && THREADS=(1 2 4 8)

# Метрики для results.csv: имя столбца и регулярка (sed -E), число - в первой группе ()
METRIC_NAMES=(@@METRIC_NAMES@@)
METRIC_PATTERNS=(@@METRIC_PATTERNS@@)

# Библиотеки бандла (OpenVINO, oneTBB...) ищем рядом со скриптом, а не в системе
export LD_LIBRARY_PATH="@@LIBRARY_DIRS@@${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

[ -x "$BENCH" ] || { echo "нет $BENCH (проверьте права: chmod +x)"; exit 1; }
[ -f "$MODEL" ] || { echo "нет модели $MODEL"; exit 1; }

# достать число из лога: extract <лог> <регулярка>; берём последнее совпадение
extract() { sed -nE "s/.*$2.*/\1/p" "$1" | tail -1; }

OUT="$HERE/results/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"
CSV="$OUT/results.csv"
echo "threads,niter,$(IFS=,; echo "${METRIC_NAMES[*]}")" > "$CSV"

for n in "${THREADS[@]}"; do
  LOG="$OUT/threads_$n.log"
  echo ">>> потоков: $n, итераций: $NITER"

  # taskset привязывает процесс к первым n ядрам
  taskset -c "0-$((n-1))" @@RUN_COMMAND@@ > "$LOG" 2>&1
  rc=$?

  if [ $rc -ne 0 ]; then
    echo "    ошибка (код $rc), см. $LOG"
    echo "$n,$NITER,FAIL" >> "$CSV"
    continue
  fi

  row="$n,$NITER"
  for pattern in "${METRIC_PATTERNS[@]}"; do
    row="$row,$(extract "$LOG" "$pattern")"
  done
  echo "$row" >> "$CSV"
  echo "    ${METRIC_NAMES[0]}: $(echo "$row" | cut -d, -f3)"
done

echo; echo "Результаты: $CSV"; cat "$CSV"
