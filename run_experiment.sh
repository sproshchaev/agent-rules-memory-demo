#!/usr/bin/env bash
# Прогон эксперимента: одна задача, три варианта правил, по N сессий агента на вариант.
# Каждая сессия идет с нуля во временном каталоге. Глобальные инструкции и личные skills
# агента изолированы: CODEX_HOME и HOME временные, из настоящего CODEX_HOME берется только вход.
#
# Запуск: ./run_experiment.sh <круг 1|2> [число прогонов на вариант, по умолчанию 3] [варианты...]
# Результат: rounds/<круг>/runs/<вариант>-<номер>/ (код после агента и сводка сессии).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ROUND="${1:?укажите круг: 1 или 2}"
N="${2:-3}"
shift $(( $# < 2 ? $# : 2 ))
RD="$ROOT/rounds/$ROUND"
if [ $# -gt 0 ]; then VARIANTS=("$@"); else VARIANTS=(none agents_md skill); fi
REAL_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
MODEL="${MODEL:-gpt-6.1-sol}"
TASK="$(cat "$RD/task.md")"

command -v codex >/dev/null || { echo "codex не найден в PATH"; exit 1; }
[ -f "$REAL_CODEX_HOME/auth.json" ] || { echo "нет $REAL_CODEX_HOME/auth.json, выполните codex login"; exit 1; }

for variant in "${VARIANTS[@]}"; do
  for i in $(seq 1 "$N"); do
    id="$variant-$i"
    out="$RD/runs/$id"
    if [ -d "$out" ]; then echo "$id уже есть, пропускаю"; continue; fi

    work="$(mktemp -d)"
    proj="$work/project"
    cp -R "$RD/project" "$proj"
    [ "$variant" = none ] || cp -R "$RD/variants/$variant/." "$proj/"
    git -C "$proj" init -q
    git -C "$proj" add -A
    git -C "$proj" -c user.name=demo -c user.email=demo@example.com commit -q -m baseline

    mkdir -p "$work/home" "$work/codex-home"
    ln -s "$REAL_CODEX_HOME/auth.json" "$work/codex-home/auth.json"

    echo "== $id"
    SECONDS=0
    HOME="$work/home" CODEX_HOME="$work/codex-home" codex exec --ephemeral --json \
      -m "$MODEL" -s workspace-write -C "$proj" -o "$work/last_message.txt" "$TASK" \
      < /dev/null > "$work/events.jsonl" 2> "$work/stderr.txt" \
      || { echo "codex завершился с ошибкой: $(tail -3 "$work/stderr.txt")"; rm -rf "$work"; exit 1; }

    mkdir -p "$out"
    rsync -a --exclude .git --exclude __pycache__ "$proj/" "$out/project/"
    cp "$work/last_message.txt" "$out/last_message.txt" 2>/dev/null || true
    python3 "$ROOT/session_meta.py" "$work/events.jsonl" "$SECONDS" "$MODEL" \
      > "$out/session.txt"
    rm -rf "$work"
  done
done

python3 "$ROOT/summarize.py"
