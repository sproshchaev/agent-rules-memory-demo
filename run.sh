#!/usr/bin/env bash
# Пересчет результатов без живой модели: проверка проверяльщика, затем сводка
# по сохраненным прогонам из runs/ и сверка с expected.txt. Код выхода 1 при расхождении.
set -euo pipefail
cd "$(dirname "$0")"
python3 selftest.py
python3 summarize.py --verify
