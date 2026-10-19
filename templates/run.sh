#!/usr/bin/env bash
# Запуск бенчмарка на плате. Лежит в корне бандла рядом с bin/, tbb/, model/.
# Использование:  ./run.sh [потоки...]      например  ./run.sh 1 4 8   (по умолчанию 1 2 4 8)
# Переменные:     NITER=5 (число итераций), MODEL=путь/к/модели.xml
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH="$HERE/bin/@@BENCH@@"
MODEL="${MODEL:-$HERE/@@MODEL@@}"
NITER="${NITER:-5}"
THREADS=("$@"); [ ${#THREADS[@]} -eq 0 ] && THREADS=(1 2 4 8)

export LD_LIBRARY_PATH="$HERE/bin:$HERE/tbb${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

[ -x "$BENCH" ] || { echo "нет $BENCH (права: chmod +x)"; exit 1; }
[ -f "$MODEL" ] || { echo "нет модели $MODEL"; exit 1; }

OUT="$HERE/results/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"
CSV="$OUT/results.csv"
echo "threads,niter,median_ms,avg_ms,min_ms,max_ms" > "$CSV"

for n in "${THREADS[@]}"; do
  LOG="$OUT/threads_$n.log"
  echo ">>> потоков: $n, итераций: $NITER"
  taskset -c "0-$((n-1))" "$BENCH" -m "$MODEL" -d CPU -hint none -api sync \
      -nthreads "$n" -nstreams 1 -nireq 1 -infer_precision f32 -niter "$NITER" \
      > "$LOG" 2>&1
  rc=$?
  # строки вида "[ INFO ] Median:  50812.3 ms"
  get() { awk -v k="$1:" '$0 ~ /\[ INFO \]/ && $4==k {print $5}' "$LOG" | tail -1; }
  if [ $rc -ne 0 ]; then
    echo "    ошибка (код $rc), см. $LOG"; echo "$n,$NITER,FAIL,,," >> "$CSV"; continue
  fi
  echo "$n,$NITER,$(get Median),$(get Average),$(get Min),$(get Max)" >> "$CSV"
  echo "    median: $(get Median) ms"
done

echo; echo "Результаты: $CSV"; cat "$CSV"
