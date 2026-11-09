"""Сводка эксперимента по сохраненным прогонам в rounds/<N>/runs/.

Для каждого прогона заново считает нарушения (check.py) и прогоняет приемочный тест
на копии кода. Пишет results.md. С ключом --verify сверяет итог с expected.txt и
возвращает код 1 при расхождении.
"""
import argparse
import ast
import sys
from pathlib import Path

from check import ROOT, ROUNDS, TITLES, acceptance, broken_keys, check, is_log_call, parse_or_none

VARIANT_TITLES = {
    "none": "без правил",
    "agents_md": "AGENTS.md",
    "skill": "AGENTS.md + skill",
}
NOTES = {
    2: {
        "uuid_id": "подсказано задачей: сигнатура второго круга требует id строкой, "
                   "и модель берет uuid4 без всяких правил",
        "log_event": "без правил модель не пишет логов в новом модуле вовсе "
                     "(колонка «Логов» ниже), формат нарушать нечем",
    },
}


def log_calls(project: Path, baseline: Path) -> int:
    """Вызовы логгера в модулях app/, которых нет в исходном проекте."""
    total = 0
    for path in (project / "app").rglob("*.py"):
        rel = path.relative_to(project).as_posix()
        tree = None if (baseline / rel).exists() else parse_or_none(path, rel)
        if tree is not None:
            total += sum(isinstance(n, ast.Call) and is_log_call(n) for n in ast.walk(tree))
    return total


def session(run: Path) -> dict:
    path = run / "session.txt"
    if not path.exists():
        return {}
    return dict(line.split(": ", 1) for line in path.read_text(encoding="utf-8").splitlines()
                if ": " in line)


def run_order(run: Path) -> tuple:
    """Порядок прогонов: вариант, затем номер числом, чтобы none-10 шел после none-9."""
    variant, idx = run.name.rsplit("-", 1)
    return variant, int(idx)


def collect(num: int) -> list:
    round_dir = ROOT / "rounds" / str(num)
    baseline = round_dir / "project"
    rows = []
    runs = [p for p in (round_dir / "runs").glob("*-*") if p.is_dir()]
    for run in sorted(runs, key=run_order):
        variant, idx = run_order(run)
        passed, total = acceptance(run / "project")
        rows.append({"variant": variant, "num": idx,
                     "broken": broken_keys(check(run / "project", baseline, ROUNDS[num])),
                     "passed": passed, "total": total,
                     "logs": log_calls(run / "project", baseline),
                     "skill_read": session(run).get("skill_read", "-")})
    return rows


def render_round(num: int, rows: list) -> list:
    keys = ROUNDS[num]
    old = ROUNDS.get(num - 1, keys)
    new = [k for k in keys if k not in old]
    groups = [("прежние", old), ("новые", new)] if new else [("все", keys)]
    notes = NOTES.get(num, {})
    by_variant = {v: [r for r in rows if r["variant"] == v] for v in VARIANT_TITLES}

    head = " | ".join(f"Нарушено, {name} {len(ks)}, в среднем" for name, ks in groups)
    lines = [f"## Круг {num}", "", f"| Вариант | Прогонов | {head} | По прогонам | Приемка |",
             "|---|---:|" + "---:|" * len(groups) + "---|---|"]
    for variant, title in VARIANT_TITLES.items():
        sel = by_variant[variant]
        if not sel:
            continue
        means = " | ".join(
            f"{sum(len(set(r['broken']) & set(ks)) for r in sel) / len(sel):.1f}"
            for _, ks in groups)
        per_run = ", ".join(str(len(r["broken"])) for r in sel)
        acc = ", ".join(f"{r['passed']}/{r['total']}" for r in sel)
        lines.append(f"| {title} | {len(sel)} | {means} | {per_run} | {acc} |")

    lines += ["", "| Проверка | " + " | ".join(VARIANT_TITLES.values()) + " |",
              "|---|" + "---:|" * len(VARIANT_TITLES)]
    for key in keys:
        cells = [f"{sum(key in r['broken'] for r in sel)}/{len(sel)}" if sel else "-"
                 for sel in by_variant.values()]
        mark = (" (новое)" if key in new else "") + ("*" if key in notes else "")
        lines.append(f"| {TITLES[key]}{mark} | " + " | ".join(cells) + " |")
    if notes:
        lines += [""] + [f"\\* {TITLES[key]}: {note}." for key, note in notes.items()]

    lines += ["", "| Прогон | Нарушено | Какие проверки | Приемка | Логов в новом модуле "
              "| SKILL.md прочитан |", "|---|---:|---|---|---:|---|"]
    for r in rows:
        lines.append(f"| {r['variant']}-{r['num']} | {len(r['broken'])} | "
                     f"{', '.join(r['broken']) or '-'} | {r['passed']}/{r['total']} | "
                     f"{r['logs']} | {r['skill_read']} |")
    return lines + [""]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    lines = ["# Результаты", ""]
    for num in ROUNDS:
        rows = collect(num)
        if rows:
            lines += render_round(num, rows)
    text = "\n".join(lines)
    (ROOT / "results.md").write_text(text, encoding="utf-8")
    print(text)
    if args.verify:
        expected = (ROOT / "expected.txt").read_text(encoding="utf-8")
        if expected != text:
            print("РАСХОЖДЕНИЕ с expected.txt")
            return 1
        print("совпадает с expected.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
