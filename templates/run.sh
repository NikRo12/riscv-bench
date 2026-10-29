#!/usr/bin/env bash
# Замер скорости на плате. Лежит в корне бандла рядом с bin/, tbb/, model/.
#
# Использование:  ./run.sh                    все сценарии подряд
#                 ./run.sh latency            один сценарий (имена - в конфиге, раздел [[run.scenarios]])
#                 ./run.sh latency 1 4        сценарий с другими значениями параметра
#                 ./run.sh 8                  сокращение: значения для первого сценария
# Переменные:     CORES=x100|a100   на каких ядрах мерить (наборы - в configs/target.toml, core_sets)
#                 NITER=5           число итераций (сценарии, где в команде есть {niter})
#                 DURATION=60       секунд на один замер (сценарии с {duration})
#                 MODEL=путь        другая модель вместо model/...
#
# Файл сгенерирован build.py из templates/run.sh: слова между @@ подставляются из конфигов.
# Править лучше конфиги и шаблон, а не готовый run.sh.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH="$HERE/@@BENCH@@"
MODEL="${MODEL:-$HERE/@@MODEL@@}"
NITER="${NITER:-5}"
DURATION="${DURATION:-60}"

# Наборы ядер платы: имя -> диапазон (из configs/target.toml)
declare -A CORE_SETS=(@@CORE_SETS@@)
CORES="${CORES:-@@DEFAULT_CORES@@}"
[ -n "${CORE_SETS[$CORES]:-}" ] || { echo "неизвестный набор ядер CORES=$CORES (есть: ${!CORE_SETS[*]})"; exit 1; }
CORE_RANGE="${CORE_SETS[$CORES]}"
CORE_FIRST="${CORE_RANGE%-*}"; CORE_LAST="${CORE_RANGE#*-}"

# Сценарии (из конфига фреймворка): параметр, значения по умолчанию, сколько ядер занять
SCENARIOS=(@@SCENARIO_NAMES@@)
declare -A SC_PARAM=(@@SC_PARAM@@)       # что перебираем: threads или batch
declare -A SC_VALUES=(@@SC_VALUES@@)     # значения по умолчанию
declare -A SC_CPUS=(@@SC_CPUS@@)         # first = первые N ядер набора (N = значение), all = весь набор
@@SCENARIO_COMMANDS@@

# Метрики для results.csv: имя столбца и регулярка (sed -E), число - в первой группе ()
METRIC_NAMES=(@@METRIC_NAMES@@)
METRIC_PATTERNS=(@@METRIC_PATTERNS@@)

# Библиотеки бандла (OpenVINO, oneTBB...) ищем рядом со скриптом, а не в системе
export LD_LIBRARY_PATH="@@LIBRARY_DIRS@@${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

[ -x "$BENCH" ] || { echo "нет $BENCH (проверьте права: chmod +x)"; exit 1; }
[ -f "$MODEL" ] || { echo "нет модели $MODEL"; exit 1; }

# Какие сценарии и значения запускать
RUN_LIST=(); VALUES=()
if [ $# -eq 0 ] || [ "$1" = all ]; then
  RUN_LIST=("${SCENARIOS[@]}")
elif [ -n "${SC_PARAM[$1]:-}" ]; then
  RUN_LIST=("$1"); shift; VALUES=("$@")
else
  RUN_LIST=("${SCENARIOS[0]}"); VALUES=("$@")
fi

# достать число из лога: extract <лог> <регулярка>; берём последнее совпадение
extract() { sed -nE "s/.*$2.*/\1/p" "$1" | tail -1; }

OUT="$HERE/results/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"
CSV="$OUT/results.csv"
echo "scenario,value,cores,$(IFS=,; echo "${METRIC_NAMES[*]}")" > "$CSV"
echo "ядра: $CORES ($CORE_RANGE)"

for sc in "${RUN_LIST[@]}"; do
  param="${SC_PARAM[$sc]}"
  if [ ${#VALUES[@]} -gt 0 ]; then values=("${VALUES[@]}"); else read -ra values <<< "${SC_VALUES[$sc]}"; fi

  for v in "${values[@]}"; do
    threads=""; batch=""; printf -v "$param" '%s' "$v"
    if [ "${SC_CPUS[$sc]}" = first ]; then
      CPUS="$CORE_FIRST-$((CORE_FIRST + v - 1))"
    else
      CPUS="$CORE_RANGE"
    fi
    LOG="$OUT/${sc}_$v.log"
    REPORT_DIR="$OUT/report_${sc}_$v"; mkdir -p "$REPORT_DIR"
    echo ">>> $sc: $param=$v, ядра $CPUS"

    "cmd_$sc"                              # собирает команду в массив CMD
    taskset -c "$CPUS" "${CMD[@]}" > "$LOG" 2>&1
    rc=$?

    if [ $rc -ne 0 ]; then
      echo "    ошибка (код $rc), см. $LOG"
      echo "$sc,$v,$CPUS,FAIL" >> "$CSV"
      continue
    fi

    row="$sc,$v,$CPUS"
    for pattern in "${METRIC_PATTERNS[@]}"; do
      row="$row,$(extract "$LOG" "$pattern")"
    done
    echo "$row" >> "$CSV"
    echo "    ${METRIC_NAMES[0]}: $(echo "$row" | cut -d, -f4)"
  done
done

echo; echo "Результаты: $CSV"; cat "$CSV"
