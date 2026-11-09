"""Позитивный и негативный контроль check.py, для каждого круга.

1. Исходный проект и эталонное решение (reference/) нарушений не дают.
2. Эталон проходит свои тесты и приемочный тест.
3. Каждый случай дает ровно ожидаемый набор нарушений: подложенное нарушение ловится только
   своей проверкой, а допустимый код (ALLOWED) нарушений не дает.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from check import DYNAMIC, ROOT, ROUNDS, acceptance, broken_keys, check

# Мутация: (файл, что заменить, на что). None вместо «что» значит дописать в конец.
SUB_MIGRATION = "migrations/003_subscriptions.sql"
STATUS_LINE = "    status TEXT NOT NULL,\n"
# Подложенные нарушения по проверкам. Каждая мутация обязана ловиться только своей проверкой.
MUTATIONS = {
    "money_int": [("app/subscriptions.py", None, "\n\ndef _x(p):\n    return float(p)\n")],
    "money_name": [("migrations/009_extra.sql", None,
                    "CREATE TABLE extra (\n    id TEXT PRIMARY KEY,\n    status TEXT NOT NULL,\n"
                    "    price_kopecks INTEGER\n);\n")],
    "utc_clock": [("app/subscriptions.py", None,
                   "\n\ndef _x():\n    from datetime import datetime\n    return datetime.now()\n")],
    "db_layer": [("app/subscriptions.py", None,
                  "\n\ndef _x(conn):\n    return conn.execute('SELECT 1')\n")],
    "app_error": [("app/subscriptions.py", None, "\n\ndef _x():\n    raise ValueError('x')\n")],
    "stdlib_only": [("app/subscriptions.py", None, "\n\ndef _x():\n    import requests\n")],
    "migrations": [("migrations/001_users.sql", None, "\n-- правка старой миграции\n")],
    "soft_delete": [("app/db.py", None,
                     "\n\ndef _x(conn):\n    conn.execute('DELETE FROM subscriptions')\n")],
    "uuid_id": [("migrations/009_extra.sql", None,
                 "CREATE TABLE extra (\n    id INTEGER PRIMARY KEY,\n    status TEXT NOT NULL\n);\n")],
    "status_field": [
        ("migrations/009_extra.sql", None,
         "CREATE TABLE extra (\n    id TEXT PRIMARY KEY,\n    cancelled_at TEXT\n);\n"),
        (SUB_MIGRATION, STATUS_LINE, ""),
        (SUB_MIGRATION, STATUS_LINE, "    status INTEGER NOT NULL,\n"),
        (SUB_MIGRATION, STATUS_LINE, "    status TEXT,\n"),
    ],
    "audit": [("app/subscriptions.py",
               '    db.add_audit(conn, "subscription", subscription_id, "cancelled", now)\n', "")],
    "log_event": [("app/subscriptions.py", None,
                   "\n\ndef _x():\n    log.info('subscription touched')\n")],
    "error_code": [("app/subscriptions.py", None,
                    "\n\ndef _x():\n    raise AppError('not_found', 'x')\n")],
}


def build(tmp: Path, round_dir: Path, with_reference: bool) -> Path:
    target = tmp / "p"
    shutil.copytree(round_dir / "project", target)
    if with_reference:
        shutil.copytree(round_dir / "reference", target, dirs_exist_ok=True)
    return target


def run_own_tests(project: Path) -> None:
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                   cwd=project, check=True, capture_output=True)


# Мутации, после которых код эталона падает: динамические проверки срабатывают заодно
# и входят в ожидаемый набор. Ключ - (проверка, номер мутации).
ALSO_DYNAMIC = {("status_field", 1)}
# Допустимый код: таблица без жизненного цикла живет без status и без нарушений.
ALLOWED = [("migrations/009_catalog.sql", None,
            "CREATE TABLE plan_catalog (\n    id TEXT PRIMARY KEY,\n    title TEXT NOT NULL\n);\n")]


def cases(keys: list) -> list:
    """(имя, мутация, ожидаемый набор нарушений) для всех проверок круга и допустимого кода."""
    result = []
    for key in keys:
        for i, mutation in enumerate(MUTATIONS[key]):
            expect = {key} | (DYNAMIC & set(keys) if (key, i) in ALSO_DYNAMIC else set())
            result.append((f"{key} #{i}", mutation, expect))
    result += [(f"допустимый код #{i}", m, set()) for i, m in enumerate(ALLOWED)]
    return result


def mutate(project: Path, mutation: tuple) -> None:
    rel, old, new = mutation
    path = project / rel
    if old is None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(new)
        return
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, rel
    path.write_text(text.replace(old, new), encoding="utf-8")


def selftest_round(num: int, tmp: Path) -> list:
    round_dir = ROOT / "rounds" / str(num)
    keys = ROUNDS[num]

    def broken(project: Path) -> set:
        return set(broken_keys(check(project, round_dir / "project", keys)))

    failures = []
    base_broken = broken(build(tmp / "a", round_dir, False)) - DYNAMIC
    if base_broken:
        failures.append(f"исходный проект дает нарушения: {sorted(base_broken)}")
    ref = build(tmp / "b", round_dir, True)
    ref_broken = broken(ref)
    if ref_broken:
        failures.append(f"эталон дает нарушения: {sorted(ref_broken)}")
    try:
        run_own_tests(ref)
    except subprocess.CalledProcessError as err:
        failures.append("эталон не проходит свои тесты:\n" + err.stderr.decode())
    passed, total = acceptance(ref)
    if passed != total:
        failures.append(f"эталон проходит приемку {passed} из {total}")
    all_cases = cases(keys)
    exact = 0
    for i, (name, mutation, expect) in enumerate(all_cases):
        project = build(tmp / f"c_{i}", round_dir, True)
        mutate(project, mutation)
        got = broken(project)
        if got == expect:
            exact += 1
        else:
            failures.append(f"{name}: ожидалось {sorted(expect)}, поймано {sorted(got)}")
    print(f"круг {num}: {exact} из {len(all_cases)} случаев дали ровно ожидаемые нарушения "
          f"({len(ALLOWED)} из них допустимый код)")
    return [f"круг {num}: {f}" for f in failures]


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        for num in ROUNDS:
            failures += selftest_round(num, Path(tmp) / str(num))
    for line in failures:
        print("FAIL", line)
    print("selftest:", "OK" if not failures else "ОШИБКИ")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
